"""The fingerprint observes files a sync would conflict in, and arm 2 sees them (#191).

The lock-conflict intent's rules must read three facts the fingerprint did not have:
which files both sides changed **so that a three-way merge conflicts**, and, in those
files, which lines of the merge base each side removed while the other kept them. These
tests pin:

* the facts on a real `lockfile_conflict` sandbox, and on hand-built removals by
  each side;
* a file both sides changed in separate hunks -- `diverged`'s overlapping state -- is
  not a conflict;
* a line both sides changed is dropped by neither;
* observing writes nothing to the repository, not even an object;
* **all three reach `as_text`** now that the intent is registered (ADR-0029).
"""

from __future__ import annotations

from pathlib import Path

from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.state_grid import LOCKFILE_STATES

FIELDS = {"merge_conflicted_files", "upstream_dropped_lines", "local_dropped_lines"}


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _lock(version: str, entries: list[str]) -> str:
    body = "".join(f'    "{entry}",\n' for entry in entries)
    return f"version = {version}\npackages = [\n{body}]\n"


def _diverge(box: Sandbox, local: str, upstream: str) -> None:
    """Commit `deps.lock` at a shared base, then a different edit on each side."""
    work = box.work
    (work / "deps.lock").write_text(_lock("0.1.0", ["corelib 0.1.0", "zlib 1.0.0"]))
    _git(work, "add", "deps.lock")
    _git(work, "commit", "-q", "-m", "base lock")
    _git(work, "push", "-q", "upstream", "main")
    base = _git(work, "rev-parse", "HEAD")
    (work / "deps.lock").write_text(upstream)
    _git(work, "commit", "-q", "-am", "upstream's lock")
    _git(work, "push", "-q", "upstream", "main")
    _git(work, "reset", "-q", "--hard", base)
    (work / "deps.lock").write_text(local)
    _git(work, "commit", "-q", "-am", "local lock")
    _git(work, "fetch", "-q", "upstream")


def test_a_lockfile_conflict_sandbox_conflicts_in_its_lock(make_sandbox) -> None:
    state = StateFingerprint.observe(make_sandbox(0, ["lockfile_conflict"]))
    assert state.merge_conflicted_files == ["deps.lock"]
    assert state.upstream_dropped_lines == [] and state.local_dropped_lines == []


def test_a_removal_by_upstream_is_seen_as_upstreams(make_sandbox) -> None:
    box = make_sandbox(0, [])
    _diverge(
        box,
        local=_lock("2.0.1", ["birch 2.0.1", "corelib 0.1.0", "zlib 1.0.0"]),
        upstream=_lock("3.4.0", ["elder 3.4.0", "corelib 0.1.0"]),
    )
    state = StateFingerprint.observe(box)
    assert state.merge_conflicted_files == ["deps.lock"]
    assert state.upstream_dropped_lines == ['    "zlib 1.0.0",']
    assert state.local_dropped_lines == [], "the version line both sides changed is neither's"


def test_a_removal_by_the_local_side_is_seen_as_local(make_sandbox) -> None:
    box = make_sandbox(0, [])
    _diverge(
        box,
        local=_lock("2.0.1", ["birch 2.0.1", "corelib 0.1.0"]),
        upstream=_lock("3.4.0", ["elder 3.4.0", "corelib 0.1.0", "zlib 1.0.0"]),
    )
    state = StateFingerprint.observe(box)
    assert state.local_dropped_lines == ['    "zlib 1.0.0",']
    assert state.upstream_dropped_lines == []


def test_separate_hunks_in_one_file_are_not_a_conflict(make_sandbox) -> None:
    """`diverged`'s overlapping state: both sides changed `app.py`, and it auto-merges."""
    state = StateFingerprint.observe(make_sandbox(0, ["diverged"]))
    assert state.conflicting_files == {"app.py"}
    assert state.merge_conflicted_files == []


def test_observing_writes_nothing_not_even_an_object(make_sandbox) -> None:
    box = make_sandbox(0, ["lockfile_conflict"])
    before = (_git(box.work, "count-objects", "-v"), _git(box.work, "status", "--porcelain"))
    StateFingerprint.observe(box)
    after = (_git(box.work, "count-objects", "-v"), _git(box.work, "status", "--porcelain"))
    assert after == before


def test_arm_2_sees_them_now_the_intent_is_registered() -> None:
    text = LOCKFILE_STATES["local_removed"].as_text()
    assert all(f"{name}: " in text for name in FIELDS)
    assert 'local_dropped_lines:     "zlib 0.1.0",' in text
