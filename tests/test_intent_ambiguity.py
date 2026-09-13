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
