"""Shared test fixtures.

The state grids are the input to every ambiguity test: four states per intent,
covering each correct resolution plus one benign state where nothing should be
done. Benign states are included deliberately -- a dispatcher that always fires
has to be catchable, and it can only be caught by states that require refusal.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from precondition_library.provider import Completion
from precondition_library.signatures import StateFingerprint

ROOT = Path(__file__).resolve().parents[1]


def git_status_porcelain() -> str:
    """The repository's `git status --porcelain`, run from the repository root."""
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ},
    ).stdout


# Snapshotted before any test runs, so "unchanged since import" proves the suite
# leaked nothing into the repository's own tree.
GIT_STATUS_AT_IMPORT = git_status_porcelain()


@pytest.fixture
def repository_unchanged():
    """Fail if the test changed the repository's own working tree.

    The assertion is "the working tree is unchanged since import", not "the
    working tree is empty". That looks weaker and is strictly stronger. An empty
    status can only pass on a pristine checkout, so a contributor running the
    suite on a branch -- which has uncommitted work by definition -- sees a red
    test with nothing to do with their change, and a real leak becomes
    indistinguishable from their own edits. "Unchanged" fails for the one thing
    the test is about, on any checkout. The comparison runs after the body.
    """
    before = GIT_STATUS_AT_IMPORT
    yield
    after = git_status_porcelain()
    assert after == before, (
        f"this test changed the repository:\nat import:\n{before}\nafter:\n{after}"
    )


class FakeProvider:
    """Scripted `Provider` for tests: a queue of completions and a call log.

    Satisfies the Protocol structurally -- no network, no key. `react.py` and
    `compile.py` are both tested against it, so it lives here rather than in one
    test file. Deliberately small: anything clever would need its own tests.

    A queued `Completion` may carry `tool_calls` instead of (or as well as) text,
    and the fake returns it unchanged, so a scripted turn can drive the
    structured function-calling path exactly as a live response would.
    """

    def __init__(self, *completions: Completion, raises: Exception | None = None) -> None:
        self._queued = list(completions)
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if self.raises is not None:
            raise self.raises
        if not self._queued:
            raise AssertionError("FakeProvider: complete() called with an empty queue")
        return self._queued.pop(0)


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
