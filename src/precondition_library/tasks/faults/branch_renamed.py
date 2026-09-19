"""Fault: upstream renamed its tracked branch; the fork still points at the old name.

Tests a different axis from the other faults: the environment's *wiring* is
stale rather than its contents. No file changed and no commit was lost, yet the
fork is broken because the branch it follows is gone from upstream, so a program
that handles this correctly has to notice that the branch it tracks no longer
exists and re-point it -- work that is tedious to re-derive and cheap to replay.

The injected state is the fork *before it has looked*: upstream's default branch
has a new name, while the clone's `branch.<local>.merge` still names the old one.
Nothing is fetched during injection, because learning the new name is the
resolution's job; fetching here would add the new remote-tracking ref and
half-repair the environment the fault is meant to present.

The old name's remote-tracking ref is left in place. A plain `git fetch` without
`--prune` leaves it, which is what a real clone shows until someone prunes, and
`StateFingerprint.observe` reads `upstream/main` directly -- deleting that ref
would make the fingerprint raise instead of reporting the staleness. So the
`branch` field is what carries the signal: it is the one branch the clone
believes it follows, and the upstream repo no longer has it.
"""

from __future__ import annotations

from pathlib import Path

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ..intent import sample_index
from ..spec import FaultSpec, GroundTruth

# Upstream's new default-branch names, chosen by seed. None is the old name:
# the fault is that the name changed. The order is part of the seed-to-name
# mapping, so appending a name would change which name an existing seed injects;
# add names deliberately.
NEW_BRANCH_NAMES = ("trunk", "develop", "default", "primary")
_NAME_SALT = "branch_renamed:name"


def renamed_branch_for_seed(seed: int) -> str:
    """The branch name upstream renames to for this seed. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree
    with the injected environment.
    """
    return NEW_BRANCH_NAMES[sample_index(seed, _NAME_SALT, len(NEW_BRANCH_NAMES))]


def _config(work: Path, key: str) -> str | None:
    """A git config value, or None when the key is unset.

    `git config --get` exits 1 for an absent key, which is a state the checker
    reports rather than raises on.
    """
    result = run_git(("config", "--get", key), cwd=work, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


class BranchRenamedFault(FaultSpec):
    name = "branch_renamed"
    description = "Upstream's default branch was renamed and the fork still tracks the old name"
    # Empty on purpose: the resolution is a ref operation, so any commit is
    # something the fault did not ask for.
    change_surface = ()

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Rename upstream's default branch; leave the clone tracking the old name.

        The local branch is not touched: `branch.<local>.merge` still names
        `refs/heads/<old>`, which now exists in no upstream repo. The name
        upstream moves to is chosen from the seed with `sample_index`, the same
        function the phrasing sampler uses, so "deterministic choice from a seed"
        has one definition here.

        Determinism needs no extra pinning: renaming a ref creates no commit, and
        the sandbox's fixed identities and dates fix the SHAs that already exist.
        """
        work = sandbox.work
        record_base(sandbox, fault="branch_renamed")

        old_name = git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=work)
        new_name = renamed_branch_for_seed(seed)
        if new_name == old_name:
            raise ValueError(f"{new_name!r} is not a rename of {old_name!r}")

        upstream = sandbox.upstream
        run_git(("branch", "-m", old_name, new_name), cwd=upstream)
        # `branch -m` in a bare repo leaves HEAD pointing at the old, now-absent
        # name; a real upstream rename moves the default branch too.
        run_git(("symbolic-ref", "HEAD", f"refs/heads/{new_name}"), cwd=upstream)

    def task_text(self, seed: int) -> str:
        return (
            "Upstream seems to have renamed its branch. Track whatever it uses now, "
            "and don't leave my fork pointing at something that no longer exists."
        )

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome: the tracked branch exists upstream and its tip is held.

        Two clauses, both read from the environment rather than from the seed.
        First, the ref `branch.<local>.merge` names must exist in the upstream
        repo -- a local branch left pointing at the deleted old name fails here,
        and that is the fault, not the fix. Second, that upstream tip must be
        contained in the local branch, so renaming the tracking without taking
        upstream's commits is not enough.

        Existence is tested against the upstream repository itself, not against
        the clone's remote-tracking ref. After a rename the clone can still hold
        a stale `refs/remotes/upstream/<old-name>`, and `git
        branch --set-upstream-to` against such a ref *succeeds* while naming a
        branch that does not exist. Rejecting that is the point of this clause.
        """
        work = sandbox.work
        branch = git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=work)
        remote = _config(work, f"branch.{branch}.remote")
        merge_ref = _config(work, f"branch.{branch}.merge")
        if not remote or not merge_ref:
            return GroundTruth(
                ok=False,
                detail=f"local branch {branch!r} does not track any upstream branch",
            )

        exists = (
            run_git(
                ("rev-parse", "--verify", merge_ref), cwd=sandbox.upstream, check=False
            ).returncode
            == 0
        )
        if not exists:
            return GroundTruth(
                ok=False,
                detail=(
                    f"local branch {branch!r} tracks {merge_ref!r}, which does not exist "
                    f"on remote {remote!r} (the upstream branch was renamed?)"
                ),
            )

        upstream_tip = git_out("rev-parse", merge_ref, cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=(
                    f"upstream {merge_ref} tip {upstream_tip[:12]} is not contained in "
                    f"local branch {branch!r}"
                ),
            )

        return GroundTruth(
            ok=True,
            detail=(
                f"local branch {branch!r} tracks {merge_ref!r}, which exists upstream, "
                "and its tip is contained"
            ),
        )


SPEC = BranchRenamedFault()
