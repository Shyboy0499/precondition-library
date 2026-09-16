"""End-to-end: live git sandbox, injected lockfile conflict, git-only checker.

The lockfile_conflict fault is the one whose wrong resolution is quiet: deleting
the conflict markers by hand *succeeds* as a command -- the branch syncs -- while
silently dropping one side's dependency. So this file pins the same directions
the other sandbox tests pin -- the fault is present after injection, the
fingerprint sees it, a wrong resolution is rejected, a correct one is accepted --
with the negative controls being the marker-deleting and marker-leaving
resolutions themselves.

The file is lock-shaped, not a real ecosystem lockfile (see the fault's module
docstring): the sandbox has no package manager, so regeneration cannot be run or
graded here. `check` therefore grades the outcome structurally -- upstream
contained, no markers, both dependencies present -- which is what makes the
dependency-dropping resolution fail.

The checker reads its ground truth from refs under `refs/sandbox/`, which the
injector records; the tests never pass the seed to `check`, so the checker cannot
cheat by re-deriving the answer from the request.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.lockfile_conflict import (
    LOCK_PATH,
    SPEC,
    local_dependency_for_seed,
    upstream_dependency_for_seed,
)

# Seeds chosen because `sample_index` selects different package names and
# versions: 0 -> local birch 0.9.5 / upstream elder 1.2.0, 3 -> local dogwood
# 1.2.0 / upstream hazel 0.9.5. Two different pairs, so a checker that
# hard-coded one could not pass both.
SEEDS = [0, 3]

_MARKER = "<<<<<<<"


def _upstream_contained(box: Sandbox) -> bool:
    """Whether upstream's tip is contained in the local branch, alone."""
    return (
        run_git(
            ("merge-base", "--is-ancestor", "upstream/main", "HEAD"),
            cwd=box.work,
            check=False,
        ).returncode
        == 0
    )


def _lock_text(box: Sandbox) -> str:
    return (box.work / LOCK_PATH).read_text(encoding="utf-8")


def _write_lock(box: Sandbox, entries: list[str]) -> None:
    """Overwrite the lock-shaped file with exactly these package entries.

    Used to stand in for the hand-edit a marker-deleting resolution performs:
    no markers remain, but only the entries named here survive.
    """
    text = (
        "# lock-shaped dependency file (generated; not a real ecosystem lockfile)\n"
        "version = 99\n"
        "packages = [\n" + "".join(f'    "{entry}",\n' for entry in entries) + "]\n"
    )
    (box.work / LOCK_PATH).write_text(text, encoding="utf-8")


def _start_conflicted_merge(box: Sandbox) -> None:
    """Fetch and merge upstream; assert the merge genuinely conflicted."""
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    result = run_git(("merge", "--no-edit", "upstream/main"), cwd=box.work, check=False)
    assert result.returncode != 0, "the injected edits were expected to conflict"
    assert _MARKER in _lock_text(box)


def _commit_resolution(box: Sandbox, message: str) -> None:
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", message), cwd=box.work)


def _shas(box: Sandbox) -> tuple[str, str, str, str]:
    return (
        run_git(("rev-parse", "HEAD"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "upstream/main"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "refs/heads/main"), cwd=box.upstream).stdout.strip(),
        run_git(("rev-parse", "refs/sandbox/lock-local-tip"), cwd=box.work).stdout.strip(),
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_injected_fault_fails_check(seed: int, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous.

    The injected state is divergence with overlapping edits, not markers: the
    conflict is produced by the sync, so the file is clean until someone tries.
    """
    box = make_sandbox(seed, ["lockfile_conflict"])
    assert _MARKER not in _lock_text(box)

    result = SPEC.check(box)
    assert not result.ok
    assert "not contained" in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_matches_injection(seed: int, make_sandbox) -> None:
    """The fingerprint sees one commit each way, both touching the same file."""
    box = make_sandbox(seed, ["lockfile_conflict"])
    fingerprint = StateFingerprint.observe(box)

    assert fingerprint.dirty_worktree is False
    assert fingerprint.upstream_ahead == 1
    assert fingerprint.upstream_behind == 1
    assert fingerprint.local_touched_files == [LOCK_PATH]
    assert fingerprint.upstream_touched_files == [LOCK_PATH]
    assert fingerprint.conflicting_files == {LOCK_PATH}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(
    ("keep", "missing_fragment"),
    [
        ("local", "upstream-added dependency"),
        ("upstream", "locally-added dependency"),
    ],
    ids=["drops-upstream", "drops-local"],
)
def test_marker_deleting_resolution_fails_check(
    seed: int, keep: str, missing_fragment: str, make_sandbox
) -> None:
    """Remove the markers by hand, keep one side; check must still say no.

    This is the fault's whole reason to exist. The command *succeeds* -- upstream
    is contained and no marker remains -- while a dependency is silently gone.
    The explicit `_upstream_contained` assertion is the point: this is not a
    failed sync, it is a successful-looking one that lost data.
    """
    box = make_sandbox(seed, ["lockfile_conflict"])
    _start_conflicted_merge(box)
    kept = (
        local_dependency_for_seed(seed) if keep == "local" else upstream_dependency_for_seed(seed)
    )
    _write_lock(box, [kept])
    _commit_resolution(box, "merge: whichever side, markers gone")

    assert _upstream_contained(box), "the wrong resolution was supposed to sync successfully"
    assert _MARKER not in _lock_text(box)

    result = SPEC.check(box)
    assert not result.ok, f"a dropped dependency was accepted: {result.detail}"
    assert missing_fragment in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_marker_leaving_attempt_fails_check(seed: int, make_sandbox) -> None:
    """A merge committed with the markers still in the file is rejected."""
    box = make_sandbox(seed, ["lockfile_conflict"])
    _start_conflicted_merge(box)
    _commit_resolution(box, "merge: markers left in place")

    assert _upstream_contained(box)
    assert _MARKER in _lock_text(box)

    result = SPEC.check(box)
    assert not result.ok
    assert "conflict markers" in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_correct_resolution_passes_check(seed: int, make_sandbox) -> None:
    """Combine both sides' entries, no markers, upstream contained."""
    box = make_sandbox(seed, ["lockfile_conflict"])
    _start_conflicted_merge(box)
    _write_lock(
        box,
        [local_dependency_for_seed(seed), upstream_dependency_for_seed(seed)],
    )
    _commit_resolution(box, "merge: keep both dependencies")

    assert _upstream_contained(box)
    result = SPEC.check(box)
    assert result.ok, result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_reproduces_commit_shas(seed: int, make_sandbox) -> None:
    """Same seed, same content: every recorded SHA must match."""
    first = make_sandbox(seed, ["lockfile_conflict"])
    shas_first = _shas(first)
    first.destroy()
    second = make_sandbox(seed, ["lockfile_conflict"])
    assert _shas(second) == shas_first


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_does_not_mutate(seed: int, make_sandbox) -> None:
    box = make_sandbox(seed, ["lockfile_conflict"])
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert after.conflicting_files == {LOCK_PATH}


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(SEEDS[0], ["lockfile_conflict"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
