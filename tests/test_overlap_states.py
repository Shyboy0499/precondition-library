"""Admission judges an overlap state by the program's own intent (issue #158, ADR-0019).

`lockfile_conflict` injects a diverged branch whose two sides touched the same file,
and the sync intent's own decision rule labels that state `merge`. Admission used to
count it as an *unrelated* state where any fire is a defect, so every compiled
diverged program in the first live build was rejected on it -- the hand-written gold
merge program passed only through an extra precondition added to dodge it.

Now a state another fault injects is judged by this intent's label: firing there is
correct when the program implements the label and a mismatch otherwise; only a state
the intent leaves unlabelled is unrelated. These tests run the real gate on real
sandboxes.
"""

from __future__ import annotations

from conftest import gold_program

from precondition_library.agents.compile import admit
from precondition_library.program import Program
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.diverged import INTENT as SYNC_INTENT
from precondition_library.tasks.faults.submodule_moved import INTENT as SUBMODULE_INTENT

MERGE_SEED = 0  # diverged seed 0 injects overlapping_files -> merge


def _merge_without_the_workaround(variant: str = "merge") -> Program:
    """Gold merge minus `local_work_beyond_the_overlap` -- a program #158 describes."""
    program = gold_program("merge")
    kept = [p for p in program.preconditions if p.name != "local_work_beyond_the_overlap"]
    assert len(kept) == len(program.preconditions) - 1
    return program.model_copy(update={"preconditions": kept, "variant": variant})


def test_lockfile_conflict_is_a_state_the_sync_intent_labels_merge() -> None:
    """The overlap the issue found, pinned so the test below means what it says."""
    box = build_sandbox(0, ["lockfile_conflict"])
    try:
        label = SYNC_INTENT.correct_variant(StateFingerprint.observe(box))
        fires = evaluate_preconditions(_merge_without_the_workaround(), box).ok
    finally:
        box.destroy()
    assert label is not None and label.id == "merge"
    assert fires, "without the workaround the merge program accepts the overlap state"


def test_a_program_firing_correctly_on_an_overlap_state_is_admitted() -> None:
    admitted, reason = admit(_merge_without_the_workaround(), "diverged", seeds=[MERGE_SEED])
    assert admitted, reason
    assert "overlap state" in reason, reason


def test_a_program_firing_on_an_overlap_state_with_the_wrong_variant_is_rejected() -> None:
    """Mislabelled `rebase`, it now fires where the intent says `merge`: a mismatch."""
    admitted, reason = admit(
        _merge_without_the_workaround(variant="rebase"), "diverged", seeds=[MERGE_SEED]
    )
    assert not admitted
    assert "overlap state" in reason and "'merge'" in reason and "'rebase'" in reason, reason


def test_the_gold_merge_program_is_still_admitted() -> None:
    """The workaround precondition is now redundant, not wrong: gold still passes."""
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
