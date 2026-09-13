"""The state space must carry enough information to decide a resolution.

If it does not, the ambiguity is not resolvable by any dispatcher and the
experiment measures nothing -- so the fields a decision rule reads are part of
the design, not an implementation detail.
"""

from __future__ import annotations

from precondition_library.signatures import StateFingerprint


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
