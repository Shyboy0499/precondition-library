"""Fault: local branch and upstream have diverged, both with unique commits.

Three resolutions, and the request text cannot tell them apart. Which is correct
depends on what the local-only commits actually contain:

  discard  the local commits are empty of file changes, so resetting to upstream
           loses no work.
  rebase   the local commits change files upstream did not, so replaying them on
           top of upstream is conflict-free and yields a linear history.
  merge    both sides changed the same file, so rewriting local history would
           discard a resolution someone already made.

The discriminators are all observable (`upstream_behind`,
`local_touched_files`, `upstream_touched_files`), which matters: arm 3 decides by
running probes, so a resolution that needed a *judgement* could not be decided by
either mechanism and the comparison would be between two blind dispatchers.
"""

from __future__ import annotations

from pathlib import Path

from ...sandbox import Sandbox, git_out, record_base, run_git, tip_contained
from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant, sample_index
from ..spec import FaultSpec, GroundTruth

# The three live states, and the resolution each is the real-world equivalent of.
# The order is part of the seed-to-state mapping, so appending to it would change
# which state an existing seed injects; add states deliberately.
INJECTED_STATES = ("empty_local_commits", "disjoint_files", "overlapping_files")
STATE_VARIANT = {
    "empty_local_commits": "discard",
    "disjoint_files": "rebase",
    "overlapping_files": "merge",
}
# One salt for the whole codebase's "deterministic choice from a seed".
_INJECTION_SALT = "diverged:inject"

# Upstream's change lands at the top of app.py; the overlapping local change
# appends at the bottom, so the two hunks do not overlap and the merge
# resolution has a conflict-free result to reach.
_UPSTREAM_PREFIX = "import os\n\n"
_LOCAL_FUNCTION = '\n\ndef farewell(name):\n    return f"bye {name}"\n'
_LOCAL_NOTE = "\nLocal note.\n"


def state_for_seed(seed: int) -> str:
    """Which of the three live states this seed injects. Deterministic."""
    return INJECTED_STATES[sample_index(seed, _INJECTION_SALT, len(INJECTED_STATES))]


def _commit(work: Path, message: str, *, allow_empty: bool = False) -> None:
    command = ["commit", "-q", "-m", message]
    if allow_empty:
        command.append("--allow-empty")
    run_git(command, cwd=work)


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _is_empty_of_changes(state: StateFingerprint) -> bool:
    """Local commits exist but change no files."""
    return state.has_local_only_commits and not state.local_touched_files


def _overlaps_upstream(state: StateFingerprint) -> bool:
    """Both sides changed at least one of the same files."""
    return state.has_local_only_commits and bool(state.conflicting_files)


def _is_disjoint_from_upstream(state: StateFingerprint) -> bool:
    """Local commits change files, none of which upstream also changed."""
    return (
        state.has_local_only_commits
        and bool(state.local_touched_files)
        and not state.conflicting_files
    )


VARIANTS = [
    ResolutionVariant(
        id="discard",
        decided_by=_is_empty_of_changes,
        rationale="Local commits change no files, so resetting to upstream loses nothing.",
    ),
    ResolutionVariant(
        id="merge",
        decided_by=_overlaps_upstream,
        rationale=(
            "Both sides changed the same file, so replaying local commits would "
            "discard a resolution and risk re-conflicting; merge keeps both."
        ),
    ),
    ResolutionVariant(
        id="rebase",
        decided_by=_is_disjoint_from_upstream,
        rationale=(
            "Local commits touch only files upstream left alone, so replaying them "
            "on top of upstream is conflict-free and keeps history linear."
        ),
    ),
]

INTENT = IntentSpec(
    name="sync_fork_with_upstream",
    fault="diverged",
    phrasings=[
        "Get this fork back in sync with upstream without losing my commits.",
        "Upstream has moved on and so have I. Sort the branch out.",
        "This branch and upstream have both changed. Bring it back into line.",
        "My fork and upstream have both moved. Make them consistent.",
        "Upstream moved ahead of me. Get me back in line with it.",
        "Reconcile this branch with upstream.",
        "I have local work and upstream has new commits. Untangle it.",
        "Something is out of step between my branch and upstream. Fix it.",
    ],
    naming_markers=["diverged", "divergence"],
    variants=VARIANTS,
    # Rebase and merge share a symptom phrase ("both changed files") that is true
    # of both situations. That shared phrase is what keeps the text a *partial*
    # signal -- a text-only dispatcher cannot tell the two apart from it -- rather
    # than fully determining the resolution (see bench/textcontrol.py).
    variant_phrasings={
        "discard": ["my local commits change no files"],
        "rebase": [
            "my edits are in files upstream left alone",
            "my branch and upstream both changed files",
        ],
        "merge": [
            "both sides touched the same files",
            "my branch and upstream both changed files",
        ],
    },
)


class DivergedFault(FaultSpec):
    name = "diverged"
    description = "Local branch and upstream both have commits the other lacks"

    def inject(self, seed: int, sandbox: Sandbox) -> None:
        """Publish the upstream commits, then replay the local-only commits on top.

        Upstream gets one commit in every variant, so the state is genuinely
        diverged. The local side is then built from the recorded base commit,
        which is what makes the local branch ahead of upstream rather than an
        ancestor of it.
        """
        state = state_for_seed(seed)
        work = sandbox.work
        base = record_base(sandbox, fault="diverged")

        # Upstream's unique commits, published to the bare repo.
        app = work / "app.py"
        app.write_text(_UPSTREAM_PREFIX + app.read_text(encoding="utf-8"), encoding="utf-8")
        run_git(("add", "-A"), cwd=work)
        _commit(work, "feat: upstream stamps the entry point")
        run_git(("push", "-q", "upstream", "main"), cwd=work)

        # Local-only commits, replayed from the base so the two sides diverge.
        run_git(("reset", "--hard", base), cwd=work)
        if state == "empty_local_commits":
            _commit(work, "chore: local note one", allow_empty=True)
            _commit(work, "chore: local note two", allow_empty=True)
        elif state == "disjoint_files":
            _append(work / "docs/readme.md", _LOCAL_NOTE)
            run_git(("add", "-A"), cwd=work)
            _commit(work, "docs: local note")
        else:
            _append(app, _LOCAL_FUNCTION)
            _append(work / "docs/readme.md", _LOCAL_NOTE)
            run_git(("add", "-A"), cwd=work)
            _commit(work, "feat: local farewell")

        local_tip = git_out("rev-parse", "HEAD", cwd=work)
        run_git(("update-ref", "refs/sandbox/local-tip", local_tip), cwd=work)
        # Leave the remote-tracking ref current so observe() can read it without
        # fetching (observe must not mutate the environment).
        run_git(("fetch", "-q", "upstream"), cwd=work)

    def task_text(self, seed: int) -> str:
        """Delegate to the intent so there is one source of truth for phrasing."""
        return INTENT.task_text(seed)

    def variant_for_seed(self, seed: int) -> str:
        """The resolution `state_for_seed` makes correct at `seed`.

        `STATE_VARIANT` is the module's declared state-to-resolution map, so
        admission's same-intent negative class reads the same mapping `inject`
        uses rather than re-deriving it; the two cannot disagree.
        """
        return STATE_VARIANT[state_for_seed(seed)]

    def check(self, sandbox: Sandbox) -> GroundTruth:
        """Grade the outcome, not the method: upstream absorbed, local work intact.

        Two clauses. First, upstream's tip must be contained in the local branch.
        Second, the file changes the local-only commits made must still be present,
        checked by reverting them from the current tree (`git apply --reverse
        --check`) -- a change that cannot be reverted from HEAD is a change that
        was destroyed. The recorded pre-injection commits live under
        `refs/sandbox/`, which no ordinary branch rewrite removes.

        The second clause is the one that matters: `git reset --hard upstream/main`
        on the overlapping state satisfies the first clause while discarding the
        user's work, and this checker must call that not-ok.
        """
        work = sandbox.work
        upstream_tip = git_out("rev-parse", "refs/heads/main", cwd=sandbox.upstream)
        if not tip_contained(work, upstream_tip):
            return GroundTruth(
                ok=False,
                detail=f"upstream tip {upstream_tip[:12]} is not contained in the local branch",
            )

        base = git_out("rev-parse", "refs/sandbox/base", cwd=work)
        local_tip = git_out("rev-parse", "refs/sandbox/local-tip", cwd=work)
        local_patch = run_git(("diff", base, local_tip), cwd=work).stdout
        if local_patch.strip():
            reverts = run_git(
                ("apply", "--reverse", "--check", "-"), cwd=work, check=False, stdin=local_patch
            )
            if reverts.returncode != 0:
                return GroundTruth(
                    ok=False,
                    detail="local-only file changes are no longer in the tree (discarded)",
                )
        return GroundTruth(
            ok=True,
            detail="upstream tip is contained in the local branch and local-only changes survive",
        )


SPEC = DivergedFault()
