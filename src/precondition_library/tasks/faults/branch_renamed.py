"""Fault: upstream renamed the tracked branch; the fork still points at the old name.

Tests a different axis from the other faults: the environment's *wiring* is
stale rather than its contents. A program that handles this correctly has to
notice the remote-tracking branch disappeared and re-point the local branch —
work that is tedious to re-derive and cheap to replay.
"""

from __future__ import annotations

from ..spec import FaultSpec, GroundTruth


class BranchRenamedFault(FaultSpec):
    name = "branch_renamed"
    description = "Upstream's default branch was renamed and the fork still tracks the old name"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        return (
            "Upstream seems to have renamed its branch. Track whatever it uses now, "
            "and don't leave my fork pointing at something that no longer exists."
        )

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1")


SPEC = BranchRenamedFault()
