"""Compile a solved task into a program, then gate it two ways.

Everything here is offline: the model is `FakeProvider`, the sandboxes are real
`create` sandboxes injected with real faults, and admission runs the compiled
body for real. The gate is the subject, so the tests are written against its
failure modes, not its happy path only: an all-accepting precondition set and a
body that does nothing must each be rejected, and a malformed reply must be a
recorded failure rather than a traceback that loses the episode's cost.

Storage is exercised in temporary directories. No test writes a program into the
committed `library/`, and the module-scoped fixture asserts that afterwards.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import FakeProvider
from pydantic import BaseModel

from precondition_library.agents.compile import admit, compile_program
from precondition_library.library import Library
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.provider import Completion, TokenUsage
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import FAULTS

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_LIBRARY = REPO_ROOT / "library"

# Seed 1 injects `empty_local_commits`, whose resolution is `discard`. The
# mapping is `diverged.state_for_seed`, the same one test_runtime_replay uses.
DISCARD_SEED = 1

_PROVENANCE = Provenance(
    compiled_from_task="test fixture",
    model="fake",
    compiler_version="test",
    episode_id="test/fixture",
)

_DISCARD_PRECONDITIONS = [
    Predicate(
        name="has_local_only_commits",
        description="The local branch is ahead of upstream.",
        probe='test "$(git rev-list --count {upstream_remote}/{upstream_branch}..HEAD)" -gt 0',
    ),
    Predicate(
        name="local_commits_change_nothing",
        description="The local-only commits touch no files.",
        probe='test -z "$(git diff --name-only {upstream_remote}/{upstream_branch}...HEAD)"',
    ),
]

_MATCHES_UPSTREAM = [
    Predicate(
        name="matches_upstream",
        description="HEAD is exactly upstream's commit.",
        probe=(
            'test "$(git rev-parse HEAD)" = "$(git rev-parse {upstream_remote}/{upstream_branch})"'
        ),
    )
]

_DISCARD_BODY = (
    "git fetch {upstream_remote}\ngit reset --hard {upstream_remote}/{upstream_branch}\n"
)


def _program(**overrides) -> Program:
    """A program equivalent to the `discard` gold resolution, with overrides."""
    base: dict = {
        "id": "discard-like",
        "intent": "sync_fork_with_upstream",
        "variant": "discard",
        "parameters": ["work_dir", "upstream_remote", "upstream_branch"],
        "preconditions": _DISCARD_PRECONDITIONS,
        "body": _DISCARD_BODY,
        "postconditions": _MATCHES_UPSTREAM,
        "provenance": _PROVENANCE,
        "status": ProgramStatus.CANDIDATE,
    }
    base.update(overrides)
    return Program(**base)


def _reply_text(**overrides) -> str:
    """The YAML a model would return for `_program()`, without caller-set fields."""
    document = _program().model_dump(mode="json")
    document.pop("provenance")
    document.pop("status")
    for key, value in overrides.items():
        if isinstance(value, list) and value and isinstance(value[0], BaseModel):
            value = [item.model_dump(mode="json") for item in value]
        document[key] = value
    return yaml.safe_dump(document, sort_keys=False)


def _completion(text: str) -> Completion:
    return Completion(text=text, usage=TokenUsage(tokens_in=10, tokens_out=5), model="fake")


def _signature(box: Sandbox) -> TaskSignature:
    """A real signature: a request plus the environment's observed fingerprint."""
    return TaskSignature(
        intent="sync_fork_with_upstream",
        fingerprint=StateFingerprint.observe(box),
        target=str(box.work),
    )


@pytest.fixture
def make_sandbox():
    """Build injected sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int = DISCARD_SEED) -> Sandbox:
        box = create(seed, ["diverged"])
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


@pytest.fixture(scope="module", autouse=True)
def committed_library_untouched():
    """Fail if a test writes into the committed library instead of a temp dir."""
    before = [program.id for program in Library(COMMITTED_LIBRARY).load_all()]
    yield
    after = [program.id for program in Library(COMMITTED_LIBRARY).load_all()]
    assert after == before, "a test stored a program in the committed library/"


# --- a right program is admitted -------------------------------------------


def test_compiled_program_is_admitted_and_stored(make_sandbox, tmp_path) -> None:
    """The whole pipeline: compile from a scripted reply, gate it, store it."""
    box = make_sandbox()
    signature = _signature(box)
    transcript = [
        {"role": "user", "content": signature.intent},
        {"role": "assistant", "content": "done"},
    ]
    fake = FakeProvider(_completion(_reply_text()))

    result = compile_program(signature, box, transcript, fake)

    assert result.ok, result.reason
    program = result.program
    assert program is not None
    assert program.status is ProgramStatus.CANDIDATE, "admission sets the status, not compile"
    assert program.provenance.model == "fake", "provenance names the model that replied"
    assert program.provenance.episode_id, "provenance names the episode"
    assert not result.warnings
    # The prompt carries the task, the observed state and the solution transcript.
    sent = fake.calls[0]
    assert signature.intent in sent["messages"][0]["content"]
    assert "upstream_behind" in sent["messages"][0]["content"]
    assert "solution_transcript" in sent["messages"][0]["content"]
    assert "defect" in sent["system"], "the specificity rule must be stated in the prompt"

    admitted, reason = admit(program, FAULTS["diverged"], seeds=[DISCARD_SEED])
    assert admitted, reason

    library = Library(tmp_path)
    library.add(program)
    library.set_status(program.id, ProgramStatus.ADMITTED)

    stored = Library(tmp_path).load_all()
    assert [item.id for item in stored] == [program.id]
    assert stored[0].status is ProgramStatus.ADMITTED


# --- the gate's reason to exist --------------------------------------------


def test_all_accepting_preconditions_are_rejected() -> None:
    """A precondition set that accepts everything must fail the negative side."""
    program = _program(
        preconditions=[Predicate(name="always", description="accepts every state", probe="true")]
    )

    admitted, reason = admit(program, FAULTS["diverged"], seeds=[DISCARD_SEED])

    assert not admitted
    assert "negative side" in reason, reason
    assert "unrelated" in reason, reason


def test_body_that_does_not_work_is_rejected(make_sandbox) -> None:
    """A body that exits zero while changing nothing fails on the positive side."""
    program = _program(body="true\n")

    admitted, reason = admit(program, FAULTS["diverged"], seeds=[DISCARD_SEED])

    assert not admitted
    assert "positive side" in reason, reason
    assert "matches_upstream" in reason, reason


def test_admission_is_deterministic() -> None:
    """Two gates over the same program return the same verdict and the same reason.

    A gate whose verdict flickered would make every downstream comparison
    meaningless, so this is asserted rather than assumed. The reason names the
    first unrelated fault that was accepted, and the unrelated faults are tried in
    sorted order, so the text is reproducible too.
    """
    assert admit(_program(), FAULTS["diverged"], seeds=[DISCARD_SEED]) == admit(
        _program(), FAULTS["diverged"], seeds=[DISCARD_SEED]
    )

    accepting = _program(
        preconditions=[Predicate(name="always", description="accepts every state", probe="true")]
    )
    first = admit(accepting, FAULTS["diverged"], seeds=[DISCARD_SEED])
    second = admit(accepting, FAULTS["diverged"], seeds=[DISCARD_SEED])
    assert first == second
    assert not first[0]


def test_empty_preconditions_are_recorded_and_then_rejected(make_sandbox) -> None:
    """Compile records an empty precondition list as a defect; the gate then refuses it."""
    box = make_sandbox()
    fake = FakeProvider(_completion(_reply_text(preconditions=[])))

    result = compile_program(_signature(box), box, [], fake)

    assert result.ok, "an empty list is a valid Program, so the parse does not fail"
    assert result.warnings, "the defect must be recorded, not silently accepted"
    assert result.program is not None
    assert not result.program.preconditions

    admitted, reason = admit(result.program, FAULTS["diverged"], seeds=[DISCARD_SEED])
    assert not admitted
    assert "negative side" in reason, reason


# --- the ambiguous intent requires a declared variant -----------------------


@pytest.mark.parametrize("variant", [None, "not-a-declared-resolution"])
def test_admit_rejects_a_program_without_a_declared_variant(variant) -> None:
    """An ambiguous intent admits only programs whose `variant` is a declared id.

    The ledger's `misfired` is `fired_variant is not None and fired_variant !=
    correct_variant`, so a program firing with `variant: null` would record
    `fired_variant=None` -- documented as "none fired" -- and count as no miss.
    A mislabelled program would be scored against the wrong resolution. Both are
    rejected here, before any sandbox runs.
    """
    program = _program(variant=variant)

    admitted, reason = admit(program, FAULTS["diverged"], seeds=[DISCARD_SEED])

    assert not admitted
    assert "declares" in reason, reason
    assert "discard" in reason, "the reason must name the ids that were allowed"


def test_admit_still_accepts_a_declared_variant() -> None:
    """The check rejects the undeclarable, not the ambiguous intent itself."""
    admitted, reason = admit(_program(variant="discard"), FAULTS["diverged"], seeds=[DISCARD_SEED])

    assert admitted, reason


def test_the_prompt_names_the_ids_the_intent_will_accept(make_sandbox) -> None:
    """The model is told what `variant` it must emit before it can get it wrong."""
    box = make_sandbox()
    fake = FakeProvider(_completion(_reply_text()))

    compile_program(
        _signature(box),
        box,
        [],
        fake,
        variant_ids=["discard", "merge", "rebase"],
    )

    system = fake.calls[0]["system"]
    assert "discard, merge, rebase" in system
    assert "__VARIANT_RULE__" not in system, "the placeholder must be replaced"


# --- malformed replies are data --------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "this is not a YAML mapping: [unclosed",
        "just a string",
        # A mapping, but not a Program: no intent, preconditions, body or postconditions.
        "id: incomplete\n",
    ],
)
def test_malformed_reply_is_a_recorded_failure(make_sandbox, reply: str) -> None:
    """The caller gets a value carrying the cost, never an unhandled exception."""
    box = make_sandbox()
    fake = FakeProvider(_completion(reply))

    result = compile_program(_signature(box), box, [], fake)

    assert not result.ok
    assert result.program is None
    assert result.reason
    assert result.usage.tokens_in == 10
    assert result.usage.tokens_out == 5


# --- compile never executes what it generates ------------------------------


def test_compile_never_executes_the_body(make_sandbox) -> None:
    """The only output of compile is data; the marker appears when replay runs it."""
    box = make_sandbox()
    marker = box.work / "compile-marker.txt"
    fake = FakeProvider(
        _completion(
            _reply_text(
                body="echo touched > compile-marker.txt\n",
                postconditions=[
                    Predicate(name="trivial", description="always holds", probe="true")
                ],
            )
        )
    )

    result = compile_program(_signature(box), box, [], fake)

    assert result.ok, result.reason
    assert result.program is not None
    assert not marker.exists(), "compile executed the body it generated"

    replayed = replay(result.program, box)
    assert replayed.ok, replayed.reason
    assert marker.exists(), "the marker must appear once replay actually runs the body"


# --- storage rules ----------------------------------------------------------


def test_add_refuses_a_non_candidate(tmp_path) -> None:
    library = Library(tmp_path)
    with pytest.raises(ValueError, match="candidate"):
        library.add(_program(status=ProgramStatus.ADMITTED))
    assert library.load_all() == []


def test_set_status_refuses_an_unknown_id(tmp_path) -> None:
    library = Library(tmp_path)
    with pytest.raises(ValueError, match="no program"):
        library.set_status("does-not-exist", ProgramStatus.ADMITTED)


def test_quarantine_is_terminal_and_nothing_is_deleted(tmp_path) -> None:
    """A quarantined program stays, and cannot be moved back to admitted."""
    library = Library(tmp_path)
    program = _program()
    library.add(program)
    library.set_status(program.id, ProgramStatus.QUARANTINED, episode_id="episode/1")

    with pytest.raises(ValueError, match="cannot move"):
        library.set_status(program.id, ProgramStatus.ADMITTED)

    stored = Library(tmp_path).load_all()
    assert [item.id for item in stored] == [program.id], "nothing is deleted"
    assert stored[0].status is ProgramStatus.QUARANTINED

    history = (tmp_path / program.id / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history) == 2
    assert json.loads(history[-1]) == {
        "program_id": program.id,
        "from": "candidate",
        "to": "quarantined",
        "episode_id": "episode/1",
    }


def test_demoted_cannot_return_to_admitted(tmp_path) -> None:
    library = Library(tmp_path)
    program = _program()
    library.add(program)
    library.set_status(program.id, ProgramStatus.ADMITTED)
    library.set_status(program.id, ProgramStatus.DEMOTED)

    with pytest.raises(ValueError, match="cannot move"):
        library.set_status(program.id, ProgramStatus.ADMITTED)


# --- library_hash -----------------------------------------------------------


def test_library_hash_is_stable_and_sensitive_to_content(tmp_path) -> None:
    library = Library(tmp_path)
    empty = library.library_hash()

    library.add(_program(id="alpha"))
    first = library.library_hash()
    assert first != empty
    assert Library(tmp_path).library_hash() == first, "the digest must not depend on the load"

    library.set_status("alpha", ProgramStatus.ADMITTED)
    assert library.library_hash() != first, "a status change is a content change"


def test_library_hash_does_not_depend_on_insertion_order(tmp_path) -> None:
    one = Library(tmp_path / "one")
    two = Library(tmp_path / "two")
    for identifier in ("alpha", "beta"):
        one.add(_program(id=identifier))
    for identifier in ("beta", "alpha"):
        two.add(_program(id=identifier))

    assert one.library_hash() == two.library_hash()


# --- the tests leave nothing behind ----------------------------------------


def test_sandboxes_are_cleaned_up() -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert ".sandboxes" not in status.stdout
