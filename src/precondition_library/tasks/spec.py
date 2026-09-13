"""What a single task family member must provide.

A fault is only admissible if it satisfies three properties, because the
ablation depends on all three:

1. It recurs, so a program has something to amortize across.
2. Its correctness is checkable by git alone, with no LLM in the loop —
   otherwise scoring an episode costs exactly what the project is trying
   to avoid paying.
3. It is branchy. A fault solvable by one aliased command has a baseline cost
   of zero, so nothing can be saved on it and the episode is dead weight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroundTruth:
    """The result of checking an environment, produced without any model."""

    ok: bool
    detail: str


class FaultSpec:
    """One member of the task family, injected deterministically."""

    name: str
    description: str

    def inject(self, seed: int, sandbox) -> None:
        """Mutate `sandbox` into the faulty state. Same seed, same state."""
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        """The request handed to the agent. Varies by seed so that repeats are
        recognisably the same *kind* of task without being the same string."""
        raise NotImplementedError("implemented per plan: phase 1")

    def check(self, sandbox) -> GroundTruth:
        """Did the environment reach the expected state? Pure git. No model."""
        raise NotImplementedError("implemented per plan: phase 1")
