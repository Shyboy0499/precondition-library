"""Admission's overlap class, and the one overlap state #191 retired (#158, ADR-0019).

`lockfile_conflict` injects a branch whose two sides touched the same file, and the sync
intent's decision rule used to label that state `merge`. #158 found admission counting
it as an *unrelated* state where any fire is a defect, and ADR-0019 made it an
**overlap state**, judged by the sync intent's own label.

#191 measured what the label claimed: on that state a plain merge stops on a conflict
inside the lock file and fails the fault's checker, and so does every other `diverged`
resolution. So `diverged`'s rules now refuse a state where a sync would conflict
(`StateFingerprint.sync_would_conflict`), and the state is unrelated to a `diverged`
program again -- this time because the program's resolution genuinely fails there.
ADR-0019's overlap class stays in `admit`; no measured fault produces an overlap state
today. These tests run the real gate on real sandboxes.
"""

from __future__ import annotations

from conftest import gold_program

from precondition_library.agents.compile import admit
from precondition_library.program import Program
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.runtime.replay import replay
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.diverged import INTENT as SYNC_INTENT
from precondition_library.tasks.faults.lockfile_conflict import SPEC as LOCK_SPEC
from precondition_library.tasks.faults.submodule_moved import INTENT as SUBMODULE_INTENT

MERGE_SEED = 0  # diverged seed 0 injects overlapping_files -> merge


def _merge_without_the_workaround(variant: str = "merge") -> Program:
    """Gold merge minus `local_work_beyond_the_overlap` -- a program #158 describes."""
    program = gold_program("merge")
    kept = [p for p in program.preconditions if p.name != "local_work_beyond_the_overlap"]
    assert len(kept) == len(program.preconditions) - 1
    return program.model_copy(update={"preconditions": kept, "variant": variant})


def test_the_sync_intent_no_longer_labels_the_lock_conflict_state() -> None:
    box = build_sandbox(0, ["lockfile_conflict"])
    try:
        state = StateFingerprint.observe(box)
        fires = evaluate_preconditions(_merge_without_the_workaround(), box).ok
    finally:
        box.destroy()
    assert state.sync_would_conflict
    assert SYNC_INTENT.correct_variant(state) is None
    assert SYNC_INTENT.acceptable_variants(state) == ()
    assert fires, "without the workaround the merge program still accepts the state"


def test_a_merge_there_fails_the_faults_checker() -> None:
    """Why the label had to go: the program the label endorsed does not fix the fault."""
    box = build_sandbox(0, ["lockfile_conflict"])
    try:
        replay(_merge_without_the_workaround(), box)
        verdict = LOCK_SPEC.check(box)
    finally:
        box.destroy()
    assert not verdict.ok, verdict.detail


def test_a_program_firing_on_the_lock_conflict_state_is_refused_as_unrelated() -> None:
    admitted, reason = admit(_merge_without_the_workaround(), "diverged", seeds=[MERGE_SEED])
    assert not admitted
    assert "lockfile_conflict" in reason and "unrelated" in reason, reason


def test_the_gold_merge_program_is_still_admitted() -> None:
    """The workaround precondition is what keeps gold off the state, and it still does."""
    admitted, reason = admit(gold_program("merge"), "diverged", seeds=[MERGE_SEED])
    assert admitted, reason


def test_a_state_with_no_submodule_is_not_a_submodule_overlap_state() -> None:
    """The restore-submodule intent must leave a repository with no submodule unlabelled.

    Without a gitlink, `observe` reports "not initialised, upstream still references it",
    and the `init` rule used to read that as an `init` state -- so every diverged state,
    and the fault-free sandbox, was an `init` overlap state for a submodule program.
    """
    for faults in ([], ["diverged"]):
        for seed in (0, 1, 2):
            box = build_sandbox(seed, faults)
            try:
                state = StateFingerprint.observe(box)
            finally:
                box.destroy()
            assert not state.has_submodule_reference
            assert SUBMODULE_INTENT.correct_variant(state) is None, (faults, seed)
