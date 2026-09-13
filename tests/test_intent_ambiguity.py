"""The state space must carry enough information to decide a resolution.

If it does not, the ambiguity is not resolvable by any dispatcher and the
experiment measures nothing -- so the fields a decision rule reads are part of
the design, not an implementation detail.
"""

from __future__ import annotations

import pytest

from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.diverged import INTENT as DIVERGED
from precondition_library.tasks.faults.submodule_moved import INTENT as SUBMODULE
from precondition_library.tasks.registry import ambiguous_intents


def test_conflicting_files_is_the_intersection(make_state) -> None:
    state = make_state(
        local_touched_files=["a.py", "b.py"],
        upstream_touched_files=["b.py", "c.py"],
    )
    assert state.conflicting_files == {"b.py"}


def test_conflicting_files_empty_when_disjoint(make_state) -> None:
    state = make_state(local_touched_files=["a.py"], upstream_touched_files=["z.py"])
    assert state.conflicting_files == set()


def test_has_local_only_commits_counts_not_flags(make_state) -> None:
    assert make_state(upstream_behind=0).has_local_only_commits is False
    assert make_state(upstream_behind=2).has_local_only_commits is True


def test_defaults_keep_existing_construction_valid() -> None:
    """Existing call sites construct fingerprints by keyword with the original
    fields; adding fields with defaults must not break them."""
    state = StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=1,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
        remotes=[],
    )
    assert state.has_local_only_commits is False
    assert state.submodule_initialised is False
    assert state.local_touched_files == []
    assert state.submodule_pin_matches_upstream is True


@pytest.mark.parametrize(
    ("state_name", "expected"),
    [
        ("benign_nothing_local", None),
        ("empty_local_commits", "discard"),
        ("disjoint_files", "rebase"),
        ("overlapping_files", "merge"),
    ],
)
def test_diverged_resolution_is_decided_by_state(state_grid, state_name, expected) -> None:
    variant = DIVERGED.correct_variant(state_grid["sync_fork_with_upstream"][state_name])
    assert (variant.id if variant else None) == expected


def test_diverged_has_three_distinct_resolutions() -> None:
    assert {v.id for v in DIVERGED.variants} == {"discard", "merge", "rebase"}
    assert DIVERGED.is_ambiguous


def test_diverged_phrasings_mostly_do_not_name_the_fault() -> None:
    assert DIVERGED.naming_fraction(range(50)) <= 0.35


def test_diverged_variants_each_explain_themselves() -> None:
    for variant in DIVERGED.variants:
        assert variant.rationale.strip(), f"{variant.id} needs a rationale"


@pytest.mark.parametrize(
    ("state_name", "expected"),
    [
        ("benign_pin_matches", None),
        ("not_initialised", "init"),
        ("pin_drifted", "repin"),
        ("upstream_dropped_it", "remove"),
    ],
)
def test_submodule_resolution_is_decided_by_state(state_grid, state_name, expected) -> None:
    variant = SUBMODULE.correct_variant(state_grid["restore_submodule_state"][state_name])
    assert (variant.id if variant else None) == expected


def test_submodule_has_three_distinct_resolutions() -> None:
    assert {v.id for v in SUBMODULE.variants} == {"init", "repin", "remove"}
    assert SUBMODULE.is_ambiguous


def test_submodule_phrasings_mostly_do_not_name_the_fault() -> None:
    assert SUBMODULE.naming_fraction(range(50)) <= 0.35


def test_every_grid_state_is_labelable(state_grid) -> None:
    """No state in the grid may raise: overlap is a defect, and a grid state that
    matches nothing but is not benign is a hole in the decision rules."""
    for intent in ambiguous_intents():
        for name, state in state_grid[intent.name].items():
            intent.correct_variant(state)  # raises on overlap


def test_each_resolution_is_reachable(state_grid) -> None:
    """Every declared variant must be the answer for at least one grid state.

    Otherwise the variant is dead weight, and the ambiguity is smaller than the
    spec claims -- an unreachable variant makes the task family look harder than
    it is, which flatters whichever arm happens to be tested on it.
    """
    for intent in ambiguous_intents():
        seen = {
            intent.correct_variant(state).id
            for state in state_grid[intent.name].values()
            if intent.correct_variant(state) is not None
        }
        assert seen == {v.id for v in intent.variants}, f"{intent.name}: unreachable variants"


def test_at_least_one_benign_state_per_intent(state_grid) -> None:
    """A dispatcher that always fires must be catchable."""
    for intent in ambiguous_intents():
        benign = [
            state
            for state in state_grid[intent.name].values()
            if intent.correct_variant(state) is None
        ]
        assert benign, f"{intent.name}: no benign state, so never-refusing cannot be detected"


def test_label_does_not_depend_on_wording(state_grid) -> None:
    """The load-bearing property of this whole change.

    Holding the state fixed and varying the seed -- and therefore the request
    text -- must not change the correct resolution. If it did, the label would be
    a property of the phrasing and the comparison would be circular.
    """
    for intent in ambiguous_intents():
        for state in state_grid[intent.name].values():
            answers = {
                (intent.correct_variant(state).id if intent.correct_variant(state) else None)
                for _ in range(1)
            }
            for seed in range(30):
                intent.task_text(seed)  # vary the request
                resolved = intent.correct_variant(state)
                answers.add(resolved.id if resolved else None)
            assert len(answers) == 1, f"{intent.name}: label moved with the wording"


def test_registry_exposes_only_intents_with_a_surface() -> None:
    names = [intent.name for intent in ambiguous_intents()]
    assert names == ["restore_submodule_state", "sync_fork_with_upstream"]  # sorted


def test_registry_intents_name_a_real_fault() -> None:
    from precondition_library.tasks import ALL_FAULTS

    for intent in ambiguous_intents():
        assert intent.fault in ALL_FAULTS


def test_every_fault_is_accounted_for() -> None:
    """Each fault is measured through an intent, or excluded on the record.

    A fault in neither set could enter a dispatch measurement carrying a fixed
    request sentence, which is the original defect: the text would be the class
    label and a text-reading dispatcher could not mis-fire. Silence is the failure
    mode, so silence is what this forbids.
    """
    from precondition_library.tasks import ALL_FAULTS
    from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK, INTENTS

    covered = {intent.fault for intent in INTENTS.values()}
    assert covered & EXCLUDED_FROM_BENCHMARK == set(), "a fault is both measured and excluded"
    assert covered | EXCLUDED_FROM_BENCHMARK == set(ALL_FAULTS), (
        f"unaccounted faults: {sorted(set(ALL_FAULTS) - covered - EXCLUDED_FROM_BENCHMARK)}"
    )
