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
        """The request handed to the agent, sampled from the intent's paraphrase
        distribution.

        Delegates to the intent so there is one source of truth per family. The
        distribution must not name the fault in most samples: when the text
        identifies the answer, the text *is* the label and a dispatch comparison
        becomes vacuous. How far that holds is measured, not assumed -- see
        bench/textcontrol.py.
        """
        raise NotImplementedError("implemented per plan: phase 1")

    def check(self, sandbox) -> GroundTruth:
        """Did the environment reach the expected state? Pure git. No model."""
        raise NotImplementedError("implemented per plan: phase 1")

    def variant_for_seed(self, seed: int) -> str | None:
        """Which declared resolution this fault's injector selects at `seed`, if any.

        Admission's same-intent negative class needs a seed whose injected state a
        resolution *other* than the program's own is correct in, and it must pick
        that seed without building a sandbox to observe: scanning seeds by building
        environments would be slow and would make the gate's cost depend on the
        search. A fault whose intent has two or more resolutions implements this
        from the same `sample_index` mapping its `inject` uses, so the seed a
        sibling is chosen from cannot disagree with the state that gets injected.

        A fault with no ambiguous intent has no sibling resolutions to expose and
        returns None; admission then builds no same-intent sandboxes for it.
        """
        return None
