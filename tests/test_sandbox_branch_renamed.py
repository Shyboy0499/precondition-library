"""End-to-end: live git sandbox, renamed upstream branch, git-only checker.

The branch_renamed fault is the wiring-only one: no file changed and no commit
was lost, yet the fork is broken because `branch.<local>.merge` names a branch
the upstream repo no longer has. Its wrong resolution is quiet in the same way
dirty_tree's is -- a command can *succeed* (`git branch --set-upstream-to`
against a stale remote-tracking ref) while leaving the fork tracking a branch
that does not exist upstream.

`check` grades the outcome, not the method: the tracked branch must exist in the
upstream repo, verified against upstream itself rather than the clone's
remote-tracking cache, and its tip must be contained in the local branch. The
tests never pass the seed to `check`, so it cannot cheat by re-deriving the
rename target from the request.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import Sandbox, create, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.branch_renamed import (
    SPEC,
    renamed_branch_for_seed,
)

# Seeds chosen because `sample_index(seed, "branch_renamed:name", 4)` selects
# different names: 0 -> trunk, 3 -> develop. Two different rename targets, so a
# checker that hard-coded one name could not pass both.
SEEDS = [0, 3]
OLD_BRANCH = "main"


@pytest.fixture
def make_sandbox():
    """Build injected sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int) -> Sandbox:
        box = create(seed, ["branch_renamed"])
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def _upstream_branches(box: Sandbox) -> set[str]:
    out = run_git(
        ("for-each-ref", "--format=%(refname:short)", "refs/heads"), cwd=box.upstream
    ).stdout
    return set(out.split())


def _tracking(box: Sandbox) -> tuple[str, str] | None:
    """(remote, merge ref) the local branch declares, or None when untracked."""
    branch = run_git(("rev-parse", "--abbrev-ref", "HEAD"), cwd=box.work).stdout.strip()
    remote = run_git(("config", "--get", f"branch.{branch}.remote"), cwd=box.work, check=False)
    merge = run_git(("config", "--get", f"branch.{branch}.merge"), cwd=box.work, check=False)
    if remote.returncode or merge.returncode:
        return None
    return remote.stdout.strip(), merge.stdout.strip()


def _upstream_ref_resolves(box: Sandbox) -> bool:
    """Whether `@{upstream}` resolves, i.e. the tracking *looks* wired up.

    This is the wrong resolution's version of dirty_tree's `_sync_looks_fine`:
    the command succeeds and git reports an upstream, but the branch it names is
    absent from the upstream repo.
    """
    return (
        run_git(("rev-parse", "--abbrev-ref", "@{upstream}"), cwd=box.work, check=False).returncode
        == 0
    )


def _follow_rename(box: Sandbox, seed: int) -> None:
    """The honest resolution: fetch to learn the new name, then re-point at it."""
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(
        ("branch", f"--set-upstream-to=upstream/{renamed_branch_for_seed(seed)}", OLD_BRANCH),
        cwd=box.work,
    )


def _track_stale_remote_tracking_ref(box: Sandbox) -> None:
    """A wrong resolution that succeeds: point at a ref only the clone has.

    `upstream/legacy` is created locally so `--set-upstream-to` accepts it, but
    no such branch exists in the upstream repo. This is the quiet failure the
    fault exists to test.
    """
    tip = run_git(("rev-parse", "HEAD"), cwd=box.work).stdout.strip()
    run_git(("update-ref", "refs/remotes/upstream/legacy", tip), cwd=box.work)
    run_git(("branch", "--set-upstream-to=upstream/legacy", OLD_BRANCH), cwd=box.work)


def _track_nonexistent_upstream_ref(box: Sandbox) -> None:
    """A wrong resolution: declare an upstream branch that does not exist."""
    run_git(("config", f"branch.{OLD_BRANCH}.merge", "refs/heads/legacy"), cwd=box.work)


def _shas(box: Sandbox, seed: int) -> tuple[str, str, str]:
    name = renamed_branch_for_seed(seed)
    return (
        run_git(("rev-parse", "HEAD"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", f"refs/heads/{name}"), cwd=box.upstream).stdout.strip(),
        run_git(("rev-parse", f"refs/heads/{OLD_BRANCH}"), cwd=box.work).stdout.strip(),
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_injected_fault_fails_check(seed: int, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous."""
    box = make_sandbox(seed)
    assert _tracking(box) == ("upstream", f"refs/heads/{OLD_BRANCH}")

    result = SPEC.check(box)
    assert not result.ok
    # The fault graded as the fault: the tracked ref is the deleted old name.
    assert f"refs/heads/{OLD_BRANCH}" in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_matches_injection(seed: int, make_sandbox) -> None:
    """`branch` carries the signal: the clone's branch is gone from upstream.

    The old name's remote-tracking ref is deliberately left stale so `observe`
    can still read it (see the fault's module docstring), which is why the
    count probes report 0/0 here -- they are reading the stale ref, not the
    renamed branch. The branch name is the field that says the wiring is stale.
    """
    box = make_sandbox(seed)
    fingerprint = StateFingerprint.observe(box)

    assert fingerprint.branch == OLD_BRANCH
    assert fingerprint.branch not in _upstream_branches(box)
    assert _upstream_branches(box) == {renamed_branch_for_seed(seed)}
    # Stale remote-tracking ref, so the diff probes are blind to the rename.
    assert fingerprint.upstream_ahead == 0
    assert fingerprint.upstream_behind == 0


@pytest.mark.parametrize(
    ("resolve", "looks_wired", "detail_fragment"),
    [
        (_track_stale_remote_tracking_ref, True, "does not exist"),
        (_track_nonexistent_upstream_ref, False, "does not exist"),
    ],
    ids=["stale-remote-tracking-ref", "nonexistent-upstream-ref"],
)
@pytest.mark.parametrize("seed", SEEDS)
def test_wrong_resolution_fails_check(
    seed, resolve, looks_wired: bool, detail_fragment, make_sandbox
) -> None:
    """Re-point the tracking at a branch upstream does not have; check must say no.

    The first case is the quiet one: `--set-upstream-to` a stale remote-tracking
    ref makes `@{upstream}` resolve again, so the fork *looks* wired up while the
    branch it names is absent upstream. That is why `check` verifies existence
    against the upstream repo rather than the clone's cache.
    """
    box = make_sandbox(seed)
    resolve(box)
    assert _upstream_ref_resolves(box) is looks_wired

    result = SPEC.check(box)
    assert not result.ok, f"a deleted upstream ref was accepted: {result.detail}"
    assert detail_fragment in result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_correct_resolution_passes_check(seed: int, make_sandbox) -> None:
    """Fetch, then re-point at whatever upstream actually uses now."""
    box = make_sandbox(seed)
    expected_name = renamed_branch_for_seed(seed)
    _follow_rename(box, seed)
    assert _tracking(box) == ("upstream", f"refs/heads/{expected_name}")
    assert _upstream_ref_resolves(box)

    result = SPEC.check(box)
    assert result.ok, result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_reproduces_state(seed: int, make_sandbox) -> None:
    """Same seed, same rename and same SHAs; renaming a ref creates no commit."""
    first = make_sandbox(seed)
    shas_first = _shas(first, seed)
    first.destroy()
    second = make_sandbox(seed)
    assert _shas(second, seed) == shas_first
    assert renamed_branch_for_seed(seed) in _upstream_branches(second)


@pytest.mark.parametrize("seed", SEEDS)
def test_observe_does_not_mutate(seed: int, make_sandbox) -> None:
    box = make_sandbox(seed)
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert after.branch == OLD_BRANCH


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(SEEDS[0])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
