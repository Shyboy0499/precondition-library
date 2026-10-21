"""What a fired program does when it is replayed, graded as an episode is (exploratory stage).

`bench.consequences` replays each dispatch arm's fires on a fresh build of the pair's state.
These tests pin its grader on real sandboxes, one case per outcome, so a figure read from it
names what happened to the repository:

* a fault's correct resolution is `fixed`;
* a wrong one that leaves the fault in place is `not fixed`, with the checker's reason;
* a body that destroys a recorded commit's object is `lost recorded state`;
* on a fault-free state, a no-op is `unchanged` and anything that moves is `changed`;
* a body the guard refuses, or one naming a parameter the state cannot bind, is `nothing ran`;
* a checker that raises is `ungradable`, not a crash of the stage.
"""

from __future__ import annotations

import pytest
from conftest import gold_program

from precondition_library.bench.consequences import (
    CHANGED,
    FIXED,
    LOST,
    NOT_FIXED,
    NOTHING_RAN,
    UNCHANGED,
    UNGRADABLE,
    consequence_of,
)
from precondition_library.bench.library_pairs import FAULT_FREE
from precondition_library.program import Program, ProgramStatus, Provenance
from precondition_library.tasks.faults import FAULTS

MERGE_SEED = 0
"""`diverged` injects its `merge` state at seed 0."""


def _program(body: str, *, parameters: list[str] | None = None) -> Program:
    return Program(
        id="under-test",
        intent="t",
        variant="v",
        parameters=parameters or [],
        preconditions=[],
        body=body,
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="t", model="m", compiler_version="v", episode_id="e", fault="x"
        ),
        status=ProgramStatus.ADMITTED,
    )


def test_a_correct_resolution_is_fixed() -> None:
    assert FAULTS["diverged"].variant_for_seed(MERGE_SEED) == "merge"
    outcome, ok, _ = consequence_of(gold_program("merge"), MERGE_SEED, "diverged")
    assert (outcome, ok) == (FIXED, True)


def test_discarding_local_commits_is_not_fixed_with_the_checkers_reason() -> None:
    outcome, ok, detail = consequence_of(
        _program("git reset -q --hard upstream/main\n"), MERGE_SEED, "diverged"
    )
    assert (outcome, ok) == (NOT_FIXED, True)
    assert detail


def test_destroying_a_recorded_commit_is_lost_state() -> None:
    body = (
        "git reset -q --hard upstream/main\n"
        "git reflog expire --expire=now --all\n"
        "git gc -q --prune=now\n"
    )
    outcome, _, detail = consequence_of(_program(body), MERGE_SEED, "diverged")
    assert outcome == LOST, detail
    assert "no longer in the repository" in detail


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("true\n", UNCHANGED),
        ("git commit -q --allow-empty -m 'nothing needed doing'\n", CHANGED),
        ("echo scratch > notes.txt\n", CHANGED),
    ],
)
def test_on_a_fault_free_state_anything_that_moves_is_changed(body: str, expected: str) -> None:
    outcome, _, _ = consequence_of(_program(body), 0, FAULT_FREE)
    assert outcome == expected


@pytest.mark.parametrize(
    ("program", "reason"),
    [
        (_program("curl -s https://example.com\n"), "refused"),
        (
            _program("git -C {submodule_path} status\n", parameters=["submodule_path"]),
            "cannot bind",
        ),
    ],
)
def test_a_body_that_never_ran_is_nothing_ran(program: Program, reason: str) -> None:
    outcome, ok, detail = consequence_of(program, 0, FAULT_FREE)
    assert (outcome, ok) == (NOTHING_RAN, False)
    assert reason in detail, detail


def test_a_checker_that_raises_is_ungradable(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(sandbox):
        raise RuntimeError("the checker could not read the state")

    monkeypatch.setattr(FAULTS["diverged"], "check", raises)
    outcome, _, detail = consequence_of(gold_program("merge"), MERGE_SEED, "diverged")
    assert outcome == UNGRADABLE
    assert "could not read the state" in detail
