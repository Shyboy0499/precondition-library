"""Fault: the worktree has uncommitted work while upstream has moved.

The archetype of the whole project. The right recovery depends on state —
whether the local edit is worth keeping, whether upstream touched the same
region, whether the edit should be stashed, rebased, or committed first — so
the solution is not a fixed command sequence and re-deriving it costs a full
LLM pass. This is a fault where compiling pays.

The injected state is exactly what the fault name documents: a tracked file
modified in the working tree and, for some seeds, an untracked file as well,
while upstream has one commit the local branch lacks. The two sides touch
disjoint files, so a sync that keeps the work has a conflict-free result to
reach. `check` grades the outcome rather than the method: upstream's tip must
be contained in the local branch *and* the recorded uncommitted work must still
be in the tree. That second clause is the point — `git reset --hard
upstream/main`, `git checkout -- .` and `git clean -fd` each make the sync look
successful while destroying the work, and must be rejected.

This fault is real but not yet measurable: it has no `IntentSpec`, so the
request text still names the fault and it stays excluded from any dispatch
measurement (issue #25).
"""

from __future__ import annotations

from ...sandbox import Sandbox, git_out, record_base, run_git, store_blob, tip_contained
from ..intent import sample_index
from ..spec import FaultSpec, GroundTruth

# The two live states this seed selects between, and the salt that chooses them.
# "Modified" is always injected; "modified_with_untracked" adds the untracked
# half of "uncommitted work". Appending a state would change which state an
# existing seed injects, so add states deliberately.
INJECTED_STATES = ("modified", "modified_with_untracked")
_UNTRACKED_SALT = "dirty_tree:untracked"

# Upstream moves `app.py`; the local work edits `docs/readme.md`, so the two
# sides are disjoint and a sync that keeps the work cannot conflict.
_UPSTREAM_FILE = "app.py"
_UPSTREAM_COMMENT = "# upstream moved on\n"
_TRACKED_FILE = "docs/readme.md"
_LOCAL_WORK = "\nLocal work in progress: keep me.\n"
_UNTRACKED_PATH = "notes/scratch.txt"
_UNTRACKED_TEXT = "scratch note, not committed yet\n"

# Refs under refs/sandbox/ keep the injected state reachable by git itself, so
# the checker stays git-only: the patch is a blob the working tree must still
# contain, and the untracked ref exists only when a file was injected.
_PATCH_REF = "refs/sandbox/dirty-patch"
_UNTRACKED_REF = "refs/sandbox/dirty-untracked"


def state_for_seed(seed: int) -> str:
    """Which live state this seed injects. Deterministic.

    One definition for "does this seed add an untracked file", shared by `inject`
    and the tests, so a test cannot disagree with the injected environment.
    """
    return INJECTED_STATES[sample_index(seed, _UNTRACKED_SALT, len(INJECTED_STATES))]


def injects_untracked(seed: int) -> bool:
    """Whether this seed injects an untracked file alongside the tracked edit."""
    return state_for_seed(seed) == "modified_with_untracked"


class DirtyTreeFault(FaultSpec):
    name = "dirty_tree"
    description = "Uncommitted local changes present while upstream has new commits"

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Publish one upstream commit, rewind local to base, then dirty the tree.

        The upstream commit is created first and pushed, so upstream is genuinely
        ahead. The local branch is then reset back to the recorded base, which is
        what makes it *behind* upstream rather than equal to it. The uncommitted
        work is written last, on top of that base, so it is a working-tree
        modification the user could still lose.

        Deterministic in the seed: `sample_index` decides whether an untracked
        file joins the tracked edit, and the pinned sandbox environment fixes the
        commit SHAs.
        """
        work = sandbox.work
        base = record_base(sandbox, fault="dirty_tree")

        # Upstream's unique commit, published to the bare repo.
        app = work / _UPSTREAM_FILE
        app.write_text(_UPSTREAM_COMMENT + app.read_text(encoding="utf-8"), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        run_git(("commit", "-q", "-m", "feat: upstream moves on"), cwd=work)
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Rewind local to base so upstream is ahead, not already merged in.
        run_git(("reset", "--hard", base), cwd=work)

        # The uncommitted work itself: a tracked modification, plus an untracked
        # file in the half of the seed space that includes one.
        with (work / _TRACKED_FILE).open("a", encoding="utf-8") as handle:
            handle.write(_LOCAL_WORK)
        store_blob(work, _PATCH_REF, run_git(("diff",), cwd=work).stdout)
        if injects_untracked(seed):
            untracked = work / _UNTRACKED_PATH
            untracked.parent.mkdir(parents=True, exist_ok=True)
            untracked.write_text(_UNTRACKED_TEXT, encoding="utf-8")
            store_blob(work, _UNTRACKED_REF, _UNTRACKED_TEXT)

        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    def task_text(self, seed: int) -> str:
        return (
            "My local uncommitted work must survive, and this fork needs to end up "
            "in sync with upstream. Sort it out."
        )

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome: upstream absorbed and the uncommitted work intact.

        Two clauses. First, upstream's tip must be contained in the local branch.
        Second, the uncommitted work recorded at injection must still be present:
        the tracked half is a patch the working tree must still reverse-apply,
        and the untracked half a file whose content must match. Both clauses are
        recorded under `refs/sandbox/`, which no ordinary branch rewrite removes.

        The second clause is what makes the destructive "fixes" fail. `reset
        --hard upstream/main`, `checkout -- .` and `clean -fd` all satisfy the
        first clause while discarding the user's work, and each is rejected here.

        The work is graded by *presence*, not by whether it stayed uncommitted:
        committing the work preserves it, and the fault's own text asks only that
        it survive. A resolution that leaves the work only in a stash is rejected,
        because the tree no longer contains it.
        """
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=f"upstream tip {upstream_tip[:12]} is not contained in the local branch",
            )

        patch = run_git(("cat-file", "-p", _PATCH_REF), cwd=work).stdout
        if patch.strip():
            reverts = run_git(
                ("apply", "--reverse", "--check", "-"), cwd=work, check=False, stdin=patch
            )
            if reverts.returncode != 0:
                return GroundTruth(
                    ok=False,
                    detail="uncommitted tracked changes are no longer in the tree (discarded)",
                )

        has_untracked = (
            run_git(("rev-parse", "--verify", _UNTRACKED_REF), cwd=work, check=False).returncode
            == 0
        )
        if has_untracked:
            # Not stripped: the checked file must match the stored bytes exactly.
            expected = run_git(("cat-file", "-p", _UNTRACKED_REF), cwd=work).stdout
            untracked = work / _UNTRACKED_PATH
            if not untracked.exists() or untracked.read_text(encoding="utf-8") != expected:
                return GroundTruth(
                    ok=False,
                    detail="uncommitted untracked work is no longer in the tree (discarded)",
                )

        return GroundTruth(
            ok=True,
            detail=(
                "upstream tip is contained in the local branch and the uncommitted work survives"
            ),
        )


SPEC = DirtyTreeFault()
