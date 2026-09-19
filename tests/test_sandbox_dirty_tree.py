"""End-to-end: live git sandbox, injected dirty tree, git-only checker.

The dirty_tree fault is the one whose wrong resolution is quiet: a `reset
--hard` or `clean -fd` makes the branch look synced while deleting the work
that was the reason for the task. So this file pins the same three directions
the diverged sandbox test pins -- the fault is present after injection, the
fingerprint sees it, a wrong resolution is rejected, a correct one is accepted
-- with the negative controls chosen to be the destructive commands themselves.

The checker reads its ground truth from refs under `refs/sandbox/`, which the
injector records; the tests never pass the seed to `check`, so the checker
cannot cheat by re-deriving the answer from the request.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.dirty_tree import SPEC, injects_untracked

# Seeds chosen because `sample_index(seed, "dirty_tree:untracked", 2)` selects
# that injected half: 0 -> modified only, 3 -> modified plus an untracked file.
MODIFIED_ONLY = 0
WITH_UNTRACKED = 3
SEEDS = [MODIFIED_ONLY, WITH_UNTRACKED]


def _sync_looks_fine(box: Sandbox) -> bool:
    """Whether upstream's tip is contained in the local branch, alone."""
    return (
        run_git(
            ("merge-base", "--is-ancestor", "upstream/main", "HEAD"),
            cwd=box.work,
            check=False,
        ).returncode
        == 0
    )


def _stash_sync_restore(box: Sandbox) -> None:
    """The shortest honest resolution: set the work aside, sync, put it back."""
    run_git(("stash", "push", "-u", "-m", "pl-sync"), cwd=box.work)
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("rebase", "upstream/main"), cwd=box.work)
    run_git(("stash", "pop"), cwd=box.work)


def _sync_then_reset_hard(box: Sandbox) -> None:
    """Syncs, loses the tracked edit. The classic silent-wrong-action."""
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("reset", "--hard", "upstream/main"), cwd=box.work)


def _sync_then_checkout_dot(box: Sandbox) -> None:
    """Syncs, then discards the tracked edit with `checkout -- .`."""
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("merge", "--ff-only", "upstream/main"), cwd=box.work)
    run_git(("checkout", "--", "."), cwd=box.work)


def _sync_then_clean_untracked(box: Sandbox) -> None:
    """Syncs and keeps the tracked edit, but deletes the untracked one."""
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("merge", "--ff-only", "upstream/main"), cwd=box.work)
    run_git(("clean", "-fd"), cwd=box.work)


def _shas(box: Sandbox) -> tuple[str, str, str, str]:
    return (
        run_git(("rev-parse", "HEAD"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "upstream/main"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "refs/heads/main"), cwd=box.upstream).stdout.strip(),
        box.recorded["patch"],
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_injected_fault_fails_check(seed: int, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous."""
    box = make_sandbox(seed, ["dirty_tree"])
    result = SPEC.check(box)
    assert not result.ok
    assert result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_matches_injection(seed: int, make_sandbox) -> None:
    """The fingerprint must see dirty work and upstream ahead, nothing else."""
    box = make_sandbox(seed, ["dirty_tree"])
    fingerprint = StateFingerprint.observe(box)

    assert fingerprint.dirty_worktree is True
    assert fingerprint.upstream_ahead == 1
    assert fingerprint.upstream_behind == 0
    assert fingerprint.local_touched_files == []
    assert fingerprint.upstream_touched_files == ["app.py"]

    status = run_git(("status", "--porcelain", "--untracked-files=all"), cwd=box.work).stdout
    assert ("notes/scratch.txt" in status) is injects_untracked(seed)


@pytest.mark.parametrize(
    ("seed", "resolve", "detail_fragment"),
    [
        (MODIFIED_ONLY, _sync_then_reset_hard, "tracked changes"),
        (MODIFIED_ONLY, _sync_then_checkout_dot, "tracked changes"),
        (WITH_UNTRACKED, _sync_then_reset_hard, "tracked changes"),
        (WITH_UNTRACKED, _sync_then_clean_untracked, "untracked work"),
    ],
    ids=["reset-hard", "checkout-dot", "reset-hard-untracked", "clean-fd-untracked"],
)
def test_wrong_resolution_fails_check(seed, resolve, detail_fragment, make_sandbox) -> None:
    """Each command syncs the branch while destroying work; check must say no.

    The explicit `_sync_looks_fine` assertion is the whole point: the wrong
    action is not a failed sync, it is a successful one that deleted the reason
    for the task.
    """
    box = make_sandbox(seed, ["dirty_tree"])
    resolve(box)
    assert _sync_looks_fine(box), "the wrong resolution was supposed to sync successfully"

    result = SPEC.check(box)
    assert not result.ok, f"destroyed work was accepted: {result.detail}"
    assert detail_fragment in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_correct_resolution_passes_check(seed: int, make_sandbox) -> None:
    """Stash, sync, restore: not a gold program, just the honest minimum."""
    box = make_sandbox(seed, ["dirty_tree"])
    _stash_sync_restore(box)
    assert _sync_looks_fine(box)
    result = SPEC.check(box)
    assert result.ok, result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_stashing_without_restoring_fails_check(seed: int, make_sandbox) -> None:
    """Work parked in a stash is not work in the tree, so the sync alone is not enough."""
    box = make_sandbox(seed, ["dirty_tree"])
    run_git(("stash", "push", "-u", "-m", "pl-sync"), cwd=box.work)
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("rebase", "upstream/main"), cwd=box.work)
    assert _sync_looks_fine(box)
    result = SPEC.check(box)
    assert not result.ok


@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_reproduces_commit_shas(seed: int, make_sandbox) -> None:
    """Same seed, same content: every recorded SHA must match."""
    first = make_sandbox(seed, ["dirty_tree"])
    shas_first = _shas(first)
    first.destroy()
    second = make_sandbox(seed, ["dirty_tree"])
    assert _shas(second) == shas_first


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_does_not_mutate(seed: int, make_sandbox) -> None:
    box = make_sandbox(seed, ["dirty_tree"])
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert after.dirty_worktree


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(MODIFIED_ONLY, ["dirty_tree"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
