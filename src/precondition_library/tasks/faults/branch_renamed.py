"""Fault: upstream renamed its tracked branch; the fork still points at the old name.

Tests a different axis from the other faults: the environment's *wiring* is
stale rather than its contents. No file changed and no commit was lost, yet the
fork is broken because the branch it follows is gone from upstream, so a program
that handles this correctly has to notice that the branch it tracks no longer
exists and re-point it -- work that is tedious to re-derive and cheap to replay.

Upstream renames its default branch *and* moves on with one commit there, while the
clone's `branch.<local>.merge` still names the old name. Each seed selects one of
three live states (#190), chosen so that different fixed resolutions are right in
different states, by this checker:

* ``plain`` -- nothing local beyond the base;
* ``local_work`` -- one local commit upstream lacks, so the sync is not a fast-forward;
* ``name_taken`` -- a local branch already has the new name, with a commit of its own.

The injected state is the fork as the trusted pre-fetch leaves a checkout (#181,
#205): fetched, and with `refs/remotes/upstream/HEAD` brought current by `git remote
set-head --auto`, but **not pruned** (the owner's decision on #190), so the old name's
remote-tracking ref is still there. A fetch does not repair anything: the wiring --
which branch the local one follows -- is the fault, and only a resolution changes it.
The state is therefore observable without fetching, as `observe` requires: upstream's
default is `upstream_default_branch`, and the stale wiring is `tracked_branch`.
"""

from __future__ import annotations

from pathlib import Path

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, sample_index
from ..spec import FaultSpec, GroundTruth

# The three live states a seed selects between, and the salt that chooses them.
# Appending a state would change which state an existing seed injects, so add
# states deliberately. Independent of the name salt, so a seed's name and state vary
# separately.
INJECTED_STATES = ("plain", "local_work", "name_taken")
_STATE_SALT = "branch_renamed:state"

# Upstream's commit on the renamed branch edits `app.py`; the local commit on the
# `local_work` state edits `docs/readme.md`, so a merge of the two is clean.
_UPSTREAM_FILE = "app.py"
_LOCAL_FILE = "docs/readme.md"
_TAKEN_FILE = "notes/side.md"

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


def state_for_seed(seed: int) -> str:
    """Which live state this seed injects. Deterministic.

    One definition shared by `inject` and the tests, so a test cannot disagree with the
    injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _STATE_SALT, len(INJECTED_STATES))]


# --- the intent (#190), defined here and not yet registered ------------------------
#
# Not in `tasks.registry.INTENTS`, so nothing measured reads it: `variant_for_seed`
# stays `None` and the fault stays excluded. Registering it is the step that changes
# measurement (the owner approved it on #190); until then it exists so its acceptable
# sets can be pinned against `check` by replay (`tests/test_branch_renamed_intent.py`).

STATE_VARIANT = {"plain": "rename", "local_work": "merge", "name_taken": "retrack"}
"""Which resolution each injected state is labelled with; what `INTENT`'s rules decide."""


def follows_a_renamed_branch(state: StateFingerprint) -> bool:
    """The family's situation (`StateFingerprint.follows_a_renamed_branch`)."""
    return state.follows_a_renamed_branch


def _has_local_commits(state: StateFingerprint) -> bool:
    return state.upstream_behind > 0


def _new_name_taken(state: StateFingerprint) -> bool:
    """A local branch other than the current one already has upstream's new name."""
    name = state.upstream_default_branch
    return name in state.local_branches and name != state.branch


def _nothing_local(state: StateFingerprint) -> bool:
    return follows_a_renamed_branch(state) and not _has_local_commits(state)


VARIANTS = [
    ResolutionVariant(
        id="rename",
        decided_by=lambda s: _nothing_local(s) and not _new_name_taken(s),
        accepted_by=lambda s: _nothing_local(s) and not _new_name_taken(s),
        rationale=(
            "Nothing local stands in the way, so the local branch takes upstream's new "
            "name and follows it, and the two stop disagreeing about what the branch is called."
        ),
    ),
    ResolutionVariant(
        id="retrack",
        decided_by=lambda s: _nothing_local(s) and _new_name_taken(s),
        accepted_by=_nothing_local,
        rationale=(
            "A local branch already has the new name, so the current branch keeps its own "
            "name and is pointed at upstream's new one, then fast-forwarded."
        ),
    ),
    ResolutionVariant(
        id="merge",
        decided_by=lambda s: follows_a_renamed_branch(s) and _has_local_commits(s),
        accepted_by=follows_a_renamed_branch,
        rationale=(
            "Local commits upstream lacks mean a fast-forward cannot take upstream's work, "
            "so the branch is pointed at the new name and upstream is merged in."
        ),
    ),
]

INTENT = IntentSpec(
    name="follow_renamed_upstream_branch",
    fault="branch_renamed",
    phrasings=[
        "My branch seems to follow something upstream no longer has. Point it at whatever "
        "upstream uses now, and keep my work.",
        "Pulling stopped working on this fork. Get it tracking upstream again without "
        "losing anything.",
        "Upstream changed something about its branches and my checkout is lost. Sort it out.",
        "Make this branch follow upstream's current main line again, and catch it up.",
        "I think upstream renamed things. Get this fork following it again.",
        "This branch's upstream looks wrong now. Fix the tracking and bring in upstream's "
        "latest work.",
        "Git says my branch's upstream is gone. Hook it back up to the right one and update it.",
        "Reconnect this branch to upstream and catch it up, without touching my other branches.",
    ],
    naming_markers=["renamed", "rename"],
    variants=VARIANTS,
    variant_phrasings={
        "rename": [
            "there is nothing of mine on this branch, and no branch here has upstream's new name"
        ],
        "retrack": ["I already have a local branch called what upstream uses now"],
        "merge": ["I made commits of my own before upstream changed things"],
    },
)


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
    # Upstream's commit and the local one: a merge or fast-forward brings either into
    # the local branch's committed diff from the base. The side branch's file is not
    # on the local branch, so it is not declared.
    change_surface = (_UPSTREAM_FILE, _LOCAL_FILE)

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Move upstream on and rename its branch; leave the clone tracking the old name.

        Upstream's commit is made in the clone and pushed, then the clone is rewound to
        the base, as `dirty_tree` does, so the commit exists only upstream. The bare
        repository then renames its branch and moves `HEAD` with it, as a real rename
        of a default branch does. The local branch's `branch.<local>.merge` still names
        `refs/heads/<old>`, which now exists in no upstream repo.

        The name upstream moves to and the state are each chosen from the seed with
        `sample_index`, under separate salts. Deterministic in the seed: the pinned
        sandbox environment fixes every commit's SHA.
        """
        work = sandbox.work
        base = record_base(sandbox, fault="branch_renamed")
        state = state_for_seed(seed)

        old_name = git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=work)
        new_name = renamed_branch_for_seed(seed)
        if new_name == old_name:
            raise ValueError(f"{new_name!r} is not a rename of {old_name!r}")

        app = work / _UPSTREAM_FILE
        app.write_text("# upstream, after the rename\n" + app.read_text(encoding="utf-8"))
        run_git(("commit", "-q", "-am", "feat: upstream moves on"), cwd=work)
        run_git(("push", "-q", "upstream", old_name), cwd=work)
        run_git(("reset", "-q", "--hard", base), cwd=work)

        upstream = sandbox.upstream
        run_git(("branch", "-m", old_name, new_name), cwd=upstream)
        # `branch -m` in a bare repo leaves HEAD pointing at the old, now-absent
        # name; a real upstream rename moves the default branch too.
        run_git(("symbolic-ref", "HEAD", f"refs/heads/{new_name}"), cwd=upstream)

        if state == "local_work":
            with (work / _LOCAL_FILE).open("a", encoding="utf-8") as handle:
                handle.write("\nLocal work, committed before the rename was noticed.\n")
            run_git(("commit", "-q", "-am", "docs: local work"), cwd=work)
            sandbox.recorded["local-tip"] = git_out("rev-parse", "HEAD", cwd=work)
        elif state == "name_taken":
            run_git(("checkout", "-q", "-b", new_name), cwd=work)
            side = work / _TAKEN_FILE
            side.parent.mkdir(parents=True, exist_ok=True)
            side.write_text("an experiment on a branch that happens to share the name\n")
            run_git(("add", _TAKEN_FILE), cwd=work)
            run_git(("commit", "-q", "-m", "wip: side experiment"), cwd=work)
            sandbox.recorded["taken-tip"] = git_out("rev-parse", "HEAD", cwd=work)
            run_git(("checkout", "-q", old_name), cwd=work)

        # What the trusted pre-fetch leaves on a checkout: fetched, upstream's HEAD
        # asked for, nothing pruned (#190). No resolution happens here.
        run_git(("fetch", "-q", "upstream"), cwd=work)
        run_git(("remote", "set-head", "upstream", "--auto"), cwd=work)

    def task_text(self, seed: int) -> str:
        return (
            "Upstream seems to have renamed its branch. Track whatever it uses now, "
            "and don't leave my fork pointing at something that no longer exists."
        )

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome: the tracked branch exists upstream, its tip is held, and
        nothing local was lost.

        Four clauses, all read from the environment rather than from the seed.
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

        Third, on the `local_work` state, the local commit's change must still be in the
        tree: a `reset --hard` onto the new branch satisfies the first two clauses
        while discarding it. Graded by presence, as `diverged` does, so a rebase that
        rewrites the commit keeps it. Fourth, on `name_taken`, the side branch's commit
        must still be reachable from some local branch: `git branch -M` onto the new
        name satisfies the first two clauses by deleting the user's branch.
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

        local_tip = sandbox.recorded.get("local-tip")
        if local_tip is not None:
            patch = run_git(("diff", sandbox.recorded["base"], local_tip), cwd=work).stdout
            reverts = run_git(
                ("apply", "--reverse", "--check", "-"), cwd=work, check=False, stdin=patch
            )
            if reverts.returncode != 0:
                return GroundTruth(
                    ok=False, detail="the local commit's work is no longer in the tree (lost)"
                )

        taken_tip = sandbox.recorded.get("taken-tip")
        if taken_tip is not None:
            holders = git_out(
                "for-each-ref",
                "--contains",
                taken_tip,
                "--format=%(refname)",
                "refs/heads/",
                cwd=work,
            )
            if not holders:
                return GroundTruth(
                    ok=False,
                    detail=(
                        f"the local branch that already had the new name lost its commit "
                        f"{taken_tip[:12]}"
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
