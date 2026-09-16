"""Arm 2: dispatch by text similarity, and the blindness that is being measured.

Arm 2 ranks admitted programs by how similar their text is to the request
(intent plus the state rendered as words). It is given the state, because
issue #4 requires both arms to receive the same representation; what it cannot
do is *evaluate* it. Every test here is offline -- no provider, no network --
and builds its library under `tmp_path` rather than touching the committed one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from precondition_library.library import (
    DEFAULT_SIMILARITY_THRESHOLD,
    Library,
    ScoredProgram,
)
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.similarity import lexical_similarity

ROOT = Path(__file__).resolve().parents[1]

INTENT = "reconcile local commits with upstream"


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(autouse=True)
def _repository_is_untouched():
    """Every library write in this file must go to `tmp_path`, not the repo.

    Compares against the status before the test rather than requiring a clean
    tree: the branch carrying this file is uncommitted while it is reviewed, and
    a real write by the test would show up as a delta.
    """
    before = _git_status()
    yield
    after = _git_status()
    assert after == before, f"this test changed the repository:\nbefore:\n{before}\nafter:\n{after}"


@pytest.fixture
def make_sandbox():
    """Build throwaway sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int, faults: list[str]) -> Sandbox:
        box = create(seed, faults)
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def _fingerprint() -> StateFingerprint:
    return StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=2,
        upstream_behind=3,
        has_locked_branch=False,
        has_submodule_reference=False,
        remotes=["origin", "upstream"],
        local_touched_files=["app.py"],
        upstream_touched_files=["app.py"],
    )


def _signature(intent: str = INTENT) -> TaskSignature:
    return TaskSignature(intent=intent, fingerprint=_fingerprint(), target="/tmp/arm-2-test")


def _predicate(description: str, probe: str = "true") -> Predicate:
    return Predicate(name="p", description=description, probe=probe)


def _program(
    program_id: str,
    description: str,
    *,
    intent: str = INTENT,
    status: ProgramStatus = ProgramStatus.ADMITTED,
    precondition: Predicate | None = None,
) -> Program:
    return Program(
        id=program_id,
        intent=intent,
        preconditions=[precondition or _predicate(description)],
        body="true",
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="similarity-dispatch test fixture",
            model="human",
            compiler_version="human",
            episode_id=f"test/{program_id}",
        ),
        status=status,
    )


def _store(
    tmp_path: Path,
    programs: list[Program],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Library:
    """A library holding `programs` at the statuses they declare.

    `Library.add` takes only a candidate, so each program is added as one and
    then moved through the real transition table. `threshold` is arm 2's floor,
    configured at construction because that is where the harness sets it.
    """
    library = Library(tmp_path, threshold=threshold)
    for program in programs:
        library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
        if program.status is not ProgramStatus.CANDIDATE:
            library.set_status(program.id, program.status)
    return library


def _query_text(signature: TaskSignature) -> str:
    """The request arm 2 matches with, per issue #4: intent plus state as text."""
    return f"{signature.intent}\n{signature.fingerprint.as_text()}"


def _program_text(program: Program) -> str:
    """A program's English, recomputed so "would score highest" is checked here.

    Deliberately independent of `library._program_text`; the two must stay in
    step, and that is the point -- if the arm's representation changes, this
    test's notion of the strongest candidate must change with it.
    """
    return " ".join(
        [
            program.intent,
            *(predicate.description for predicate in program.preconditions),
            *(predicate.description for predicate in program.postconditions),
        ]
    )


def test_ranking_orders_by_textual_distance(tmp_path) -> None:
    """The nearest program by surface overlap comes first, and the scores fall."""
    near = _program("a-near", "the dirty worktree has local commits ahead of upstream")
    mid = _program("b-mid", "the submodule is initialised")
    far = _program("c-far", "frosting and sprinkles", intent="decorate a cake")
    # The floor is set to 0.0 so the zero-overlap program still appears and its
    # place in the order is what is checked; the default floor is exercised in
    # `test_threshold_is_a_floor`.
    library = _store(tmp_path, [near, mid, far], threshold=0.0)

    matched = library.match_semantic(_signature())

    assert all(isinstance(item, ScoredProgram) for item in matched)
    assert [item.program.id for item in matched] == ["a-near", "b-mid", "c-far"]
    assert matched[0].score > matched[1].score > matched[2].score

    assert [item.program.id for item in library.match_semantic(_signature(), limit=2)] == [
        "a-near",
        "b-mid",
    ]


def test_threshold_is_a_floor(tmp_path) -> None:
    """A query with no shared word is dropped; lowering the floor admits it.

    The two libraries differ only in the threshold passed to `Library`, which is
    where the harness configures it, so this also pins that the floor reaches
    `match_semantic` through the library rather than a per-call default.
    """
    unrelated = _program("a-unrelated", "frosting and sprinkles", intent="decorate a cake")
    default_floor = _store(tmp_path / "default", [unrelated])
    lowered = _store(tmp_path / "lowered", [unrelated], threshold=0.0)
    signature = _signature(intent="xyzzy plugh")

    assert DEFAULT_SIMILARITY_THRESHOLD > 0, "the default must be a real floor"
    assert default_floor.match_semantic(signature) == []

    admitted = lowered.match_semantic(signature)
    assert [item.program.id for item in admitted] == ["a-unrelated"]
    assert admitted[0].score == 0.0


def test_only_admitted_programs_are_dispatchable(tmp_path) -> None:
    """A candidate and a quarantined program that outscore the admitted one are not returned."""
    admitted = _program("a-admitted", "the submodule is initialised")
    candidate = _program(
        "b-candidate",
        "the dirty worktree has local commits ahead of upstream",
        status=ProgramStatus.CANDIDATE,
    )
    quarantined = _program(
        "c-quarantined",
        "the dirty worktree has local commits ahead of upstream",
        status=ProgramStatus.QUARANTINED,
    )
    library = _store(tmp_path, [admitted, candidate, quarantined])

    # Not vacuous: all three are stored, and both excluded ones would score
    # higher than the admitted program on the arm's own text.
    assert len(library.load_all()) == 3
    query = _query_text(_signature())
    assert lexical_similarity(query, _program_text(candidate)) > lexical_similarity(
        query, _program_text(admitted)
    )
    assert lexical_similarity(query, _program_text(quarantined)) > lexical_similarity(
        query, _program_text(admitted)
    )

    matched = library.match_semantic(_signature())
    assert [item.program.id for item in matched] == ["a-admitted"]


def test_dispatch_is_deterministic(tmp_path) -> None:
    """The same query and programs give the same order, scores, and fingerprint text."""
    near = _program("a-near", "the dirty worktree has local commits ahead of upstream")
    mid = _program("b-mid", "the submodule is initialised")
    far = _program("c-far", "frosting and sprinkles", intent="decorate a cake")
    library = _store(tmp_path, [near, mid, far])

    first = library.match_semantic(_signature())
    second = library.match_semantic(_signature())
    assert [(item.program.id, item.score) for item in first] == [
        (item.program.id, item.score) for item in second
    ]

    fingerprint = _fingerprint()
    assert fingerprint.as_text() == fingerprint.as_text()
    assert fingerprint.as_text() == _fingerprint().as_text(), "equal states render identically"


def test_similarity_returns_a_program_its_preconditions_reject(make_sandbox, tmp_path) -> None:
    """Arm 2's blindness: a similar program fires even though its probes say no.

    This is the mis-fire the primary metric counts. The program below would
    reject the environment if its precondition were run, yet text similarity
    returns it because the arm sees the state only as words. A test that made
    arm 2 state-aware would be testing a different experiment and could not
    observe this failure at all.
    """
    box = make_sandbox(21, [])
    rejecting = _program(
        "a-similar",
        "the dirty worktree has local commits ahead of upstream",
        precondition=_predicate(
            "the dirty worktree has local commits ahead of upstream",
            probe="test -f definitely-not-here",
        ),
    )
    library = _store(tmp_path, [rejecting])

    verdict = evaluate_preconditions(rejecting, box)
    assert verdict.ok is False, "fixture is not a mis-fire unless the probes reject the env"

    matched = library.match_semantic(_signature())
    assert [item.program.id for item in matched] == ["a-similar"], (
        "arm 2 returned nothing: the arm is state-aware, so this is a different experiment"
    )
