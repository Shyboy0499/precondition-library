"""The fingerprint observes the branch wiring, without rendering it yet (#190, step 1).

The branch-renamed intent's rules must read three facts the fingerprint did not have:
which upstream branch the current branch is configured to follow, which branch
upstream now calls its default, and which local branches exist. These tests pin:

* all three are observed from git, on a harness sandbox and on an existing checkout;
* the default is read from `refs/remotes/<remote>/HEAD`, which a plain fetch leaves
  alone and the trusted pre-fetch (#205) brings current -- so a rename shows only
  once something has asked upstream, and nothing here fetches;
* **none reaches `as_text`** until the intent is registered, so every measured arm-2
  text, and every measured number, is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from precondition_library.checkout import open_checkout
from precondition_library.sandbox import run_git
from precondition_library.signatures import _NOT_YET_RENDERED, StateFingerprint
from precondition_library.tasks.state_grid import STATE_GRID

WIRING = {"tracked_branch", "upstream_default_branch", "local_branches"}


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def test_a_clean_sandbox_tracks_main_and_records_no_default(make_sandbox) -> None:
    state = StateFingerprint.observe(make_sandbox(0, []))
    assert state.tracked_branch == "main"
    assert state.upstream_default_branch == "", "a harness clone records no remote HEAD"
    assert state.local_branches == ["main"]


def test_a_rename_shows_once_upstream_has_been_asked(make_sandbox) -> None:
    """Built by hand, so the observation is pinned whatever an injector leaves."""
    box = make_sandbox(0, [])
    _git(box.upstream, "branch", "-m", "main", "trunk")
    _git(box.upstream, "symbolic-ref", "HEAD", "refs/heads/trunk")

    before = StateFingerprint.observe(box)
    assert (before.tracked_branch, before.upstream_default_branch) == ("main", "")

    # What the trusted pre-fetch does on a checkout: fetch, then ask upstream for HEAD.
    _git(box.work, "fetch", "-q", "upstream")
    _git(box.work, "remote", "set-head", "upstream", "--auto")
    _git(box.work, "branch", "-q", "trunk")  # a local branch already has the new name

    after = StateFingerprint.observe(box)
    assert after.tracked_branch == "main", "the wiring itself is still stale"
    assert after.upstream_default_branch == "trunk"
    assert after.local_branches == ["main", "trunk"]


def test_a_checkout_reads_its_own_remote_after_the_pre_fetch(tmp_path) -> None:
    origin = tmp_path / "origin.git"
    run_git(("init", "-q", "--bare", "-b", "main", str(origin)), cwd=tmp_path)
    seed = tmp_path / "seed"
    run_git(("clone", "-q", str(origin), str(seed)), cwd=tmp_path)
    _git(seed, "checkout", "-q", "-b", "main")
    (seed / "base").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "base")
    _git(seed, "commit", "-q", "-m", "base")
    _git(seed, "push", "-q", "origin", "main")

    work = tmp_path / "work"
    run_git(("clone", "-q", str(origin), str(work)), cwd=tmp_path)
    _git(origin, "branch", "-m", "main", "trunk")
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/trunk")

    env = open_checkout(work, scratch=tmp_path)  # pre-fetch, then set-head --auto
    try:
        state = StateFingerprint.observe(env)
    finally:
        env.destroy()
    assert state.tracked_branch == "main"
    assert state.upstream_default_branch == "trunk"
    assert state.local_branches == ["main"]


def test_arm_2_does_not_see_them_until_the_intent_is_registered() -> None:
    assert _NOT_YET_RENDERED == WIRING
    for states in STATE_GRID.values():
        for state in states.values():
            assert not any(name in state.as_text() for name in WIRING)
    seen = StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=0,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
        tracked_branch="main",
        upstream_default_branch="trunk",
        local_branches=["main", "trunk"],
    )
    assert "trunk" not in seen.as_text(), "observed, not shown to arm 2"
