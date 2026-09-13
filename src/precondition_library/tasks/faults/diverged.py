"""Fault: local branch and upstream have diverged, both with unique commits.

Branchy because the correct move depends on facts the agent must discover:
are the local commits worth keeping, do they conflict, and is a merge or a
rebase the right history shape? A blind `git reset --hard upstream/main`
"succeeds" while destroying the user's commits, which is precisely the class
of silent failure a precondition-gated program should prevent.
"""

from __future__ import annotations

from ..spec import FaultSpec, GroundTruth


class DivergedFault(FaultSpec):
    name = "diverged"
    description = "Local branch and upstream both have commits the other lacks"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        return (
            "This branch and upstream have both moved on. Get the fork back in sync "
            "with upstream without losing my commits."
        )

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1")


SPEC = DivergedFault()
