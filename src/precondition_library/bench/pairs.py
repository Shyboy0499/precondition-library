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

    @property
    def is_negative(self) -> bool:
        return self.correct_variant is None


def label(intent: IntentSpec, seed: int, state: StateFingerprint) -> LabelledPair:
    """Label one (intent, state) instance. Pure: no environment, no model."""
    resolved = intent.correct_variant(state)
    return LabelledPair(
        intent=intent.name,
        seed=seed,
        state=state,
        correct_variant=resolved.id if resolved is not None else None,
        task_text=intent.task_text(seed),
        ambiguous=intent.is_ambiguous,
    )


def labelled_pairs(
    intent: IntentSpec,
    states: Sequence[StateFingerprint],
    seeds: Sequence[int],
) -> list[LabelledPair]:
    """Cross the given states with the given seeds.

    Every state is paired with every seed, because the label must be invariant
    under the request's wording: if relabelling moved with the text, the label
    would be a property of the phrasing and the exercise would be circular.
    """
    pairs = [label(intent, seed, state) for state in states for seed in seeds]
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
