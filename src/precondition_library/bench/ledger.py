"""The episode ledger: one JSONL line per episode, the raw material of the result.

Every number in the write-up is a grouping over this file, so it records more
than the headline metric. In particular `cached_tokens_in` is kept separate
from `tokens_in` because provider-side prompt caching can make the ReAct
baseline look cheaper than the work it performed, and that would quietly
flatter whichever arm benefits most. Dispatch-tuning parameters are recorded
per episode too, so a reviewer can tell a tuned comparison from an untuned one.

Nothing in this module computes results; that is `bench.report`'s job.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from ..program import EpisodeOutcome


class Arm(StrEnum):
    """The three conditions. Each builds its own library from an empty start."""

    REACT = "react"
    SEMANTIC = "semantic"
    PRECONDITION = "precondition"


class EpisodeRecord(BaseModel):
    """One episode. Fields are flat on purpose: the ledger must stay greppable."""

    arm: Arm
    task_id: str
    fault_type: str
    occurrence_index: int
    """1 for the first time this fault type is seen, 2 for the second, and so on.
    Grouping by this field is what produces the cost-vs-repeat curve."""
    seed: int

    tokens_in: int
    tokens_out: int
    cached_tokens_in: int = 0
    llm_calls: int
    wall_clock_s: float

    outcome: EpisodeOutcome
    """How the arm's mechanism completed. See `EpisodeOutcome`: this is not
    whether the episode was correct, which is derived from the facts below."""

    correct_variant: str | None
    """Ground truth: the resolution this state requires, or None if it is benign.
    Defined by the intent's decision rules, in separate code from the programs'
    probe strings, so a wrong precondition cannot make its own program look right.

    Required, with no default, because None is a meaningful answer ("this state
    needs nothing done"). A defaulted field could be forgotten and silently read
    as a benign state, which would turn a missing fact into a wrong one."""
    fired_variant: str | None = None
    """The resolution the program that actually ran implements; None if none fired."""
    ground_truth_ok: bool | None
    """Whether the environment reached the expected state, checked by git alone.
    None means it was not checked, which happens only for INVALID episodes.
    Also required: "not checked" must be passed deliberately, never inherited."""

    program_id: str | None = None
    dispatch_score: float | None = None
    """Similarity score for arm 2; None for the other arms."""
    admitted: bool | None = None
    refusal_reason: str | None = None
    timed_out: bool = False
    """Set when a replay exceeded its timeout. Kept beside `outcome` rather than
    folded into it, since a timeout is a failure mode of the runtime while
    `outcome` describes how the episode ended."""

    model: str
    """Exact model identifier used for this episode. Provider-side model drift
    mid-experiment silently invalidates a comparison, so it is recorded per
    episode and a version change invalidates the affected run."""

    @property
    def misfired(self) -> bool:
        """A program fired that was not the ground-truth resolution.

        Deliberately independent of final state, and of `outcome`: a wrong fire
        often ends in a successful episode because the arm falls back to the agent.
        That quadrant -- misfired and successful -- is the one the primary metric
        exists to count, and a single `outcome` value could not express it.
        """
        return self.fired_variant is not None and self.fired_variant != self.correct_variant

    @property
    def succeeded(self) -> bool:
        """Whether the episode reached the expected state. Separate from `misfired`."""
        return self.ground_truth_ok is True


def append(path: Path, record: EpisodeRecord) -> None:
    """Append one episode. Must be crash-safe: a killed run should still leave
    every completed episode on disk, since episodes are expensive to reproduce."""
    raise NotImplementedError("implemented per plan: phase 1")


def read(path: Path) -> list[EpisodeRecord]:
    """Read the ledger back. Malformed trailing lines are reported, not skipped."""
    raise NotImplementedError("implemented per plan: phase 1")
