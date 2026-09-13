"""Fault: the worktree has uncommitted work while upstream has moved.

The archetype of the whole project. The right recovery depends on state —
whether the local edit is worth keeping, whether upstream touched the same
region, whether the edit should be stashed, rebased, or committed first — so
the solution is not a fixed command sequence and re-deriving it costs a full
LLM pass. This is a fault where compiling pays.
"""

from __future__ import annotations

from ..spec import FaultSpec, GroundTruth


class DirtyTreeFault(FaultSpec):
    name = "dirty_tree"
    description = "Uncommitted local changes present while upstream has new commits"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        return (
            "My local uncommitted work must survive, and this fork needs to end up "
            "in sync with upstream. Sort it out."
        )

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1")


SPEC = DirtyTreeFault()
