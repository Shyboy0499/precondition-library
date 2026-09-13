"""Labelled (state, resolution) pairs -- the primary metric's raw material.

The spec moved the primary metric to a dispatch-level comparison at matched
coverage. That needs something an episode loop cannot provide: a label per
decision, independent of any agent's behaviour. This module derives those labels
from the intents' own decision rules, which are ground truth and deliberately NOT
the programs' probe strings (issue #9) -- a wrong precondition must not be able to
make its own program look correct.

Why this seam lives here rather than in the dispatch-level harness (issue #5):
issue #3 requires an AUC control and mismatch scored "on the ambiguous subset,
with the denominator reported". Neither exists without per-instance labels, and
the label definition must be frozen before any arm is built, or the comparison
can be tuned into existence. Issue #5 adds the threshold sweep and coverage
curves on top of this module; it should not also have to define what a wrong
answer is.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from ..signatures import StateFingerprint
from ..tasks.intent import IntentSpec


class LabelledPair(BaseModel):
    """One dispatch decision, with its answer."""

    intent: str
    seed: int
    state: StateFingerprint
    correct_variant: str | None
    """None means no resolution is correct: the environment needs nothing done, so
    every program must refuse to fire. Negative examples are half the point -- a
    dispatcher that always fires can only be caught by them."""
    task_text: str
    ambiguous: bool
    """True when the intent has two or more resolutions, so the text alone cannot decide."""
    informed: bool
    """Whether the request used wording that reveals the situation.

    Recorded per pair because the two regimes answer different questions: on
    uninformed requests the text carries no signal, so a dispatch comparison
    measures state-reading; on informed requests the wording nearly gives the
    resolution away, which is the boundary condition where the mechanism is not
    needed at all. Pooling them produces a number that means neither.
    """

    @property
    def is_negative(self) -> bool:
        return self.correct_variant is None


def label(
    intent: IntentSpec,
    seed: int,
    state: StateFingerprint,
    *,
    uninformed: bool = False,
) -> LabelledPair:
    """Label one (intent, state) instance. Pure: no environment, no model.

    `uninformed=True` samples the shared distribution instead of the state's
    declared wording: the request someone sends when they do not know what is
    wrong. The label is a function of state alone either way, which is what makes
    the regime a factor that can be varied without moving the answer.
    """
    resolved = intent.correct_variant(state)
    return LabelledPair(
        intent=intent.name,
        seed=seed,
        state=state,
        correct_variant=resolved.id if resolved is not None else None,
        task_text=intent.task_text(seed) if uninformed else intent.task_text(seed, state),
        ambiguous=intent.is_ambiguous,
        informed=False if uninformed else intent.uses_informed_wording(state),
    )


def labelled_pairs(
    intent: IntentSpec,
    states: Sequence[StateFingerprint],
    seeds: Sequence[int],
) -> list[LabelledPair]:
    """Cross the given states with the given seeds, in both request regimes.

    Every state is paired with every seed once in the channel it declares, plus a
    second, uninformed pair whenever the declared channel is informed: a user can
    send a vague request about a state that is not vague, and that is the regime
    the primary claim is measured in. States whose declared channel already is
    the shared distribution (benign states) get one pair, since the channels
    coincide there.

    The label is a function of state alone -- `label` passes the state to the
    sampler so that wording and resolution are recorded together, but wording is
    *allowed* to carry signal about the resolution: it is the label's invariance
    under state, not under wording, that keeps the exercise from being circular.
    """
    pairs = [label(intent, seed, state) for state in states for seed in seeds]
    pairs.extend(
        label(intent, seed, state, uninformed=True)
        for state in states
        for seed in seeds
        if intent.uses_informed_wording(state)
    )
    if not pairs:
        raise ValueError("produced no pairs; check states and seeds are non-empty")
    return pairs


def decision_is_correct(pair: LabelledPair, candidate_variant: str) -> bool:
    """Would replaying a program that implements `candidate_variant` be right?

    This is the grading function for a dispatch decision, and the reason
    `Program.variant` exists: without it a wrong answer is undefinable.
    """
    return pair.correct_variant is not None and candidate_variant == pair.correct_variant


def ambiguous_subset(pairs: Iterable[LabelledPair]) -> list[LabelledPair]:
    """Only the pairs on which a dispatcher comparison means anything."""
    return [pair for pair in pairs if pair.ambiguous]


def positive_subset(pairs: Iterable[LabelledPair]) -> list[LabelledPair]:
    """Pairs where some program should fire."""
    return [pair for pair in pairs if not pair.is_negative]


def denominator_report(pairs: Iterable[LabelledPair]) -> dict[str, int]:
    """Every rate this repository reports must come with its denominator."""
    materialised = list(pairs)
    positive = positive_subset(materialised)
    return {
        "pairs": len(materialised),
        "ambiguous": len(ambiguous_subset(materialised)),
        "positive": len(positive),
        "negative": len(materialised) - len(positive),
    }
