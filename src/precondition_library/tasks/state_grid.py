"""The declared state grid: which fingerprint stands for which state of which fault.

Ground truth about *states*, declared rather than observed, so a caller can cross many states
with seeds without paying to build a sandbox for each. It lives in the package rather than the
test suite because `bench` needs it: measuring whether a similarity scorer can tell which
resolution a state needs, from the text, is a bench-side question (issue #104), and a grid only
tests could reach would have forced that measurement into a test.

Two things keep a declaration from drifting away from the injectors it describes.
`tests/test_sandbox_diverged.py` checks the declared grid against what a real sandbox observes,
and `tests/test_intent_ambiguity.py` checks that every grid state is labelable and that each
resolution is reachable in it -- so a state added to a fault without a fingerprint here, or a
fingerprint nothing resolves, is a test failure rather than a quiet gap.

`tests/conftest.py` imports this and exposes it as the `state_grid` fixture; nothing else should
re-declare a state fingerprint.
"""

from __future__ import annotations

from typing import Any

from ..signatures import StateFingerprint


def declared_state(**overrides: Any) -> StateFingerprint:
    base: dict[str, Any] = {
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


# sync_fork_with_upstream: three resolutions, plus the benign state.
DIVERGED_STATES = {
    "benign_nothing_local": declared_state(upstream_touched_files=["app.py"]),
    "empty_local_commits": declared_state(
        upstream_behind=2, local_touched_files=[], upstream_touched_files=["app.py"]
    ),
    "disjoint_files": declared_state(
        upstream_behind=2,
        local_touched_files=["docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
    "overlapping_files": declared_state(
        upstream_behind=2,
        local_touched_files=["app.py", "docs/readme.md"],
        upstream_touched_files=["app.py"],
    ),
}

# restore_submodule_state: three resolutions, plus the benign state.
SUBMODULE_STATES = {
    "benign_pin_matches": declared_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=True,
    ),
    "not_initialised": declared_state(
        has_submodule_reference=True,
        submodule_initialised=False,
        submodule_pin_matches_upstream=False,
    ),
    "pin_drifted": declared_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
    ),
    "upstream_dropped_it": declared_state(
        has_submodule_reference=True,
        submodule_initialised=True,
        submodule_pin_matches_upstream=False,
        upstream_still_references_submodule=False,
    ),
}

# keep_uncommitted_work_and_sync (#189, ADR-0027): three resolutions, plus the benign state.
DIRTY_TREE_STATES = {
    "benign_clean": declared_state(upstream_ahead=1, upstream_touched_files=["app.py"]),
    "disjoint": declared_state(
        dirty_worktree=True,
        upstream_ahead=1,
        upstream_touched_files=["app.py"],
        dirty_files=["docs/readme.md"],
    ),
    "same_file": declared_state(
        dirty_worktree=True,
        upstream_ahead=1,
        upstream_touched_files=["app.py"],
        dirty_files=["app.py"],
    ),
    "collision": declared_state(
        dirty_worktree=True,
        upstream_ahead=1,
        upstream_touched_files=["app.py", "notes/scratch.txt"],
        dirty_files=["docs/readme.md"],
        untracked_upstream_collisions=["notes/scratch.txt"],
    ),
}

# follow_renamed_upstream_branch (#190): three resolutions, plus the benign state.
# Declared for the intent `tasks.faults.branch_renamed.INTENT`, which is defined but not
# yet registered, so it is deliberately not in `STATE_GRID` below: everything that walks
# the grid reads registered intents, and adding these would put an unmeasured intent in
# it. Upstream renamed `main` to `trunk` and moved on by one commit.
BRANCH_RENAMED_STATES = {
    "benign_not_renamed": declared_state(
        upstream_ahead=1,
        upstream_touched_files=["app.py"],
        tracked_branch="main",
        upstream_default_branch="main",
        local_branches=["main"],
    ),
    "plain": declared_state(
        upstream_ahead=1,
        upstream_touched_files=["app.py"],
        tracked_branch="main",
        upstream_default_branch="trunk",
        local_branches=["main"],
    ),
    "local_work": declared_state(
        upstream_ahead=1,
        upstream_behind=1,
        local_touched_files=["docs/readme.md"],
        upstream_touched_files=["app.py"],
        tracked_branch="main",
        upstream_default_branch="trunk",
        local_branches=["main"],
    ),
    "name_taken": declared_state(
        upstream_ahead=1,
        upstream_touched_files=["app.py"],
        tracked_branch="main",
        upstream_default_branch="trunk",
        local_branches=["main", "trunk"],
    ),
}

STATE_GRID: dict[str, dict[str, StateFingerprint]] = {
    "sync_fork_with_upstream": DIVERGED_STATES,
    "restore_submodule_state": SUBMODULE_STATES,
    "keep_uncommitted_work_and_sync": DIRTY_TREE_STATES,
}
