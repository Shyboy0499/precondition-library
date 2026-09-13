"""Shared test fixtures.

The state grids are the input to every ambiguity test: four states per intent,
covering each correct resolution plus one benign state where nothing should be
done. Benign states are included deliberately -- a dispatcher that always fires
has to be catchable, and it can only be caught by states that require refusal.
"""

from __future__ import annotations

import pytest

from precondition_library.signatures import StateFingerprint


# `upstream_ahead` is how many commits upstream has that HEAD lacks; `upstream_behind`
# is how many HEAD has that upstream lacks. They describe the same ref pair from
# opposite sides, so a state cannot be both without being incoherent.
def _make_state(**overrides) -> StateFingerprint:
    base = {
        "dirty_worktree": False,
        "branch": "main",
        "upstream_ahead": 3,
        "upstream_behind": 0,
        "has_locked_branch": False,
        "has_submodule_reference": False,
        "remotes": ["origin", "upstream"],
    }
    base.update(overrides)
    return StateFingerprint(**base)


@pytest.fixture
def make_state():
    """Build a fingerprint from a baseline, overriding only the fields a test cares about."""
    return _make_state


# sync_fork_with_upstream: three resolutions, plus the benign state.
DIVERGED_STATES = {
    "benign_nothing_local": _make_state(upstream_touched_files=["app.py"]),
    "empty_local_commits": _make_state(
        upstream_behind=2, local_touched_files=[], upstream_touched_files=["app.py"]
    ),
    "disjoint_files": _make_state(
        upstream_behind=2,
        local_touched_files=["docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
    "overlapping_files": _make_state(
        upstream_behind=2,
        local_touched_files=["app.py", "docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
}

# restore_submodule_state: three resolutions, plus the benign state.
SUBMODULE_STATES = {
    "benign_pin_matches": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=True,
    ),
    "not_initialised": _make_state(
        has_submodule_reference=True,
        submodule_initialised=False,
        submodule_pin_matches_upstream=False,
    ),
    "pin_drifted": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
    ),
    "upstream_dropped_it": _make_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
        upstream_still_references_submodule=False,
    ),
}

STATE_GRID: dict[str, dict[str, StateFingerprint]] = {
    "sync_fork_with_upstream": DIVERGED_STATES,
    "restore_submodule_state": SUBMODULE_STATES,
}


@pytest.fixture
def state_grid() -> dict[str, dict[str, StateFingerprint]]:
    return STATE_GRID
