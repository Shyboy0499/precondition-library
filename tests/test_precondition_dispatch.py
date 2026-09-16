"""Arm 3: a real sandbox, real probes, and the dispatch gate that reads them.

The matcher's whole claim is that an environment decides which program fires.
That claim is only worth anything if the matcher says *no* to the states a
program was not written for, so every positive here is paired with a negative
control, and the negative control uses a different fault's injector for the same
reason admission does: it is the closest thing to an unrelated state the
repository can build without a model.

Everything runs offline against throwaway sandboxes and a `tmp_path` library.
The committed library is never written to -- the autouse fixture below fails the
test if anything in this file dirties the repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from precondition_library.library import Library
from precondition_library.program import (
    Predicate,
    Program,
    ProgramStatus,
    Provenance,
)
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults.diverged import INTENT as DIVERGED_INTENT
from precondition_library.tasks.faults.submodule_moved import state_for_seed

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "bench" / "gold" / "sync_fork_with_upstream.yaml"
SUBMODULE_GOLD = ROOT / "bench" / "gold" / "restore_submodule_state.yaml"

# `conftest.py`'s grid declares seed 2 as the disjoint state, whose resolution is
# `rebase`. Reusing it here means the positive fixture is the real-world
# equivalent the grid already describes, not a state invented for this test.
DIVERGED_SEED = 2


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
    tree: the branch carrying this file is itself uncommitted while it is
    reviewed, and a real write by the test would show up as a delta.
    """
    before = _git_status()
    yield
    after = _git_status()
    assert after == before, f"this test changed the repository:\nbefore:\n{before}\nafter:\n{after}"


@pytest.fixture
def make_sandbox():
    """Build faulted sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int, faults: list[str]) -> Sandbox:
        box = create(seed, faults)
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def _gold_program(variant: str) -> Program:
    """One committed gold resolution, as a `Program`."""
    document = yaml.safe_load(GOLD.read_text(encoding="utf-8"))
    entry = next(item for item in document["programs"] if item["variant"] == variant)
    return Program.model_validate(entry)


def _submodule_gold_program(variant: str) -> Program:
    """One committed `restore_submodule_state` resolution, where `submodule_path` is needed."""
    document = yaml.safe_load(SUBMODULE_GOLD.read_text(encoding="utf-8"))
    entry = next(item for item in document["programs"] if item["variant"] == variant)
    return Program.model_validate(entry)


def _seed_for_state(state: str) -> int:
    """A seed whose `submodule_moved` injection is `state`."""
    for seed in range(64):
        if state_for_seed(seed) == state:
            return seed
    raise AssertionError(f"no seed in 0..63 injects {state!r}")


def _predicate(name: str, probe: str) -> Predicate:
    return Predicate(name=name, description=name, probe=probe)


def _program(
    program_id: str,
    preconditions: list[Predicate],
    status: ProgramStatus = ProgramStatus.ADMITTED,
) -> Program:
    return Program(
        id=program_id,
        intent="sync_fork_with_upstream",
        variant=None,
        parameters=["work_dir", "upstream_remote", "upstream_branch"],
        preconditions=preconditions,
        body="true",
        postconditions=[_predicate("noop", "true")],
        provenance=Provenance(
            compiled_from_task="precondition-dispatch test fixture",
            model="human",
            compiler_version="human",
            episode_id=f"test/{program_id}",
        ),
        status=status,
    )


def _store(tmp_path: Path, programs: list[Program]) -> Library:
    """A library holding `programs` at the statuses they declare.

    `Library.add` takes only a candidate, so each program is added as one and
    then moved through the real transition table. Quarantining a candidate is a
    legal transition; a demoted fixture is not needed here.
    """
    library = Library(tmp_path)
    for program in programs:
        library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
        if program.status is not ProgramStatus.CANDIDATE:
            library.set_status(program.id, program.status)
    return library


def _signature(box: Sandbox, seed: int) -> TaskSignature:
    """A real signature. Arm 3 does not read it; the seam requires one."""
    return TaskSignature(
        intent=DIVERGED_INTENT.task_text(seed),
        fingerprint=StateFingerprint.observe(box),
        target=str(box.root),
    )


def test_matching_gold_program_dispatches(make_sandbox, tmp_path) -> None:
    """The state its resolution fits accepts the program's preconditions."""
    box = make_sandbox(DIVERGED_SEED, ["diverged"])
    rebase = _gold_program("rebase").model_copy(update={"status": ProgramStatus.ADMITTED})
    library = _store(tmp_path, [rebase])

    result = evaluate_preconditions(rebase, box)
    assert result.ok, result.detail
    assert [item.name for item in result.predicates] == [
        predicate.name for predicate in rebase.preconditions
    ]

    matched = library.match_preconditions(_signature(box, DIVERGED_SEED), box)
    assert [program.id for program in matched] == [rebase.id]


def test_unrelated_state_is_rejected(make_sandbox, tmp_path) -> None:
    """A different fault's sandbox must not accept the same program.

    This is the negative side admission depends on, checked at the dispatch
    layer rather than only inside the gate: a matcher that returned everything
    would make the positive test above meaningless.
    """
    rebase = _gold_program("rebase").model_copy(update={"status": ProgramStatus.ADMITTED})
    library = _store(tmp_path, [rebase])

    matching = make_sandbox(DIVERGED_SEED, ["diverged"])
    matched = library.match_preconditions(_signature(matching, DIVERGED_SEED), matching)
    assert [program.id for program in matched] == [rebase.id]

    unrelated = make_sandbox(0, ["dirty_tree"])
    result = evaluate_preconditions(rebase, unrelated)
    assert not result.ok, f"rebase preconditions accepted a dirty_tree sandbox: {result.detail}"
    assert any(not item.ok for item in result.predicates), "a rejection must name what failed"

    assert library.match_preconditions(_signature(unrelated, 0), unrelated) == []


def test_specificity_orders_most_specific_first(make_sandbox, tmp_path) -> None:
    """More preconditions first, so a general program cannot shadow a targeted one.

    The ids sort the opposite way (`a-` before `b-`), so an implementation that
    fell back on directory order would return the general program first and fail.
    """
    box = make_sandbox(11, [])
    general = _program("a-general", [_predicate("has_checkout", "test -d .git")])
    specific = _program(
        "b-specific",
        [
            _predicate("has_checkout", "test -d .git"),
            _predicate("has_app", "test -f app.py"),
        ],
    )
    library = _store(tmp_path, [general, specific])

    matched = library.match_preconditions(_signature(box, 11), box)
    assert [program.id for program in matched] == ["b-specific", "a-general"]


def test_non_admitted_programs_are_never_returned(make_sandbox, tmp_path) -> None:
    """Only `admitted` is dispatchable; rule 1 is a safety property, not advice."""
    box = make_sandbox(12, [])
    holds = [_predicate("has_checkout", "test -d .git")]
    admitted = _program("a-admitted", holds)
    candidate = _program("b-candidate", holds, status=ProgramStatus.CANDIDATE)
    quarantined = _program("c-quarantined", holds, status=ProgramStatus.QUARANTINED)
    library = _store(tmp_path, [admitted, candidate, quarantined])

    # Not vacuous: all three are stored and all three would match on probes alone.
    assert len(library.load_all()) == 3
    matched = library.match_preconditions(_signature(box, 12), box)
    assert [program.id for program in matched] == [admitted.id]


def test_nothing_matching_returns_an_empty_list(make_sandbox, tmp_path) -> None:
    """The fallback path is `[]`, not an exception."""
    box = make_sandbox(13, [])
    only = _program("a-absent", [_predicate("absent", "test -f definitely-not-here")])
    library = _store(tmp_path, [only])

    assert evaluate_preconditions(only, box).ok is False
    assert library.match_preconditions(_signature(box, 13), box) == []


# --- a program needing `submodule_path` -------------------------------------


def test_submodule_program_preconditions_evaluate_on_a_submodule_sandbox(make_sandbox) -> None:
    """A gold `restore_submodule_state` program's probes run and hold, not raise.

    Before `submodule_path` was bound, every one of these programs raised on an
    unbound placeholder -- so this is the regression that pins the binding, and
    the observable surface arm 3's half of the comparison depends on.
    """
    box = make_sandbox(_seed_for_state("init"), ["submodule_moved"])
    program = _submodule_gold_program("init")

    result = evaluate_preconditions(program, box)

    assert result.ok, result.detail
    assert [item.name for item in result.predicates] == [
        predicate.name for predicate in program.preconditions
    ]


def test_submodule_program_preconditions_fail_without_a_submodule(make_sandbox) -> None:
    """No submodule means the preconditions do not hold -- a non-match, not a crash.

    A dispatch (or admission's negative side) meeting this program on a
    repository with no submodule must see a failed predicate, not an exception;
    the observed text names why. An unknown placeholder still raises, which is a
    different path (`test_substitute_raises_on_an_unknown_placeholder`).
    """
    box = make_sandbox(0, [])
    program = _submodule_gold_program("init")

    result = evaluate_preconditions(program, box)

    assert not result.ok
    assert all(not item.ok for item in result.predicates)
    assert all(item.observed.startswith("not applicable") for item in result.predicates)
