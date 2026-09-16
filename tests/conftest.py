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
import yaml

from precondition_library.bench.ledger import Arm, EpisodeRecord
from precondition_library.library import DEFAULT_SIMILARITY_THRESHOLD, Library
from precondition_library.program import EpisodeOutcome, Program, ProgramStatus
from precondition_library.provider import Completion
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "bench" / "gold"


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


# (seed, resolution) for the three injected `diverged` states. The seed selects
# the state `diverged.state_for_seed` injects; the resolution is that state's gold
# program. Shared so `test_runtime_replay.py` and `test_sandbox_diverged.py`
# cannot disagree about which seed builds which state.
GOLD_CASES: dict[str, tuple[int, str]] = {
    "empty_local_commits": (1, "discard"),
    "disjoint_files": (2, "rebase"),
    "overlapping_files": (0, "merge"),
}


def gold_programs(intent: str = "sync_fork_with_upstream") -> list[Program]:
    """Every committed gold resolution for `intent`, in file order."""
    document = yaml.safe_load((GOLD_DIR / f"{intent}.yaml").read_text(encoding="utf-8"))
    return [Program.model_validate(entry) for entry in document["programs"]]


def gold_program(variant: str, intent: str = "sync_fork_with_upstream") -> Program:
    """One committed gold resolution, as a `Program`."""
    return next(program for program in gold_programs(intent) if program.variant == variant)


def make_record(
    *,
    arm: Arm = Arm.PRECONDITION,
    outcome: EpisodeOutcome = EpisodeOutcome.FALLBACK,
    **overrides,
) -> EpisodeRecord:
    """An `EpisodeRecord` from a baseline, overriding only the fields a test cares about.

    `arm` and `outcome` are keyword parameters rather than overrides so a caller
    can set a different baseline for a whole module without restating the other
    twelve fields; every other field goes through `overrides`.
    """
    base: dict[str, Any] = {
        "arm": arm,
        "task_id": "sync_fork_with_upstream/seed-1",
        "fault_type": "diverged",
        "occurrence_index": 1,
        "seed": 1,
        "tokens_in": 0,
        "tokens_out": 0,
        "llm_calls": 0,
        "wall_clock_s": 0.0,
        "outcome": outcome,
        "model": "test",
        "correct_variant": "merge",
        "ground_truth_ok": True,
    }
    base.update(overrides)
    return EpisodeRecord(**base)


def store_programs(
    path: Path,
    programs: list[Program],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Library:
    """A library holding `programs` at the statuses they declare.

    `Library.add` takes only a candidate, so each program is added as one and
    then moved through the real transition table. `threshold` is arm 2's floor,
    configured at construction because that is where the harness sets it.
    """
    library = Library(path, threshold=threshold)
    for program in programs:
        library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
        if program.status is not ProgramStatus.CANDIDATE:
            library.set_status(program.id, program.status)
    return library


@pytest.fixture
def make_sandbox():
    """Build a sandbox from `(seed, faults)` and destroy it however the test ends.

    One definition, so the teardown is identical everywhere: every sandbox built
    through this fixture is destroyed after the test, including when an assertion
    fails. A wrong teardown leaks a `.sandboxes/` root, which is why this is a
    fixture rather than each test module owning a copy.
    """
    live: list[Sandbox] = []

    def build(seed: int, faults: list[str]) -> Sandbox:
        box = create(seed, faults)
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()
