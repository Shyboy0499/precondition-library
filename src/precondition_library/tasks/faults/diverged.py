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

from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant
from ..spec import FaultSpec, GroundTruth


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
)


class DivergedFault(FaultSpec):
    name = "diverged"
    description = "Local branch and upstream both have commits the other lacks"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1 (issue #4)")

    def task_text(self, seed: int) -> str:
        """Delegate to the intent so there is one source of truth for phrasing."""
        return INTENT.task_text(seed)

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1 (issue #9)")


SPEC = DivergedFault()
