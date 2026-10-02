"""Arm 2b: a soft vote over arm 3's own probe features, and the claim it can restate.

Issue #7's arm 2b is "a soft classifier over the SAME probe features [as arm 3] with
a learned threshold -- if 2b ties arm 3, hard conjunctive executable predicates add
nothing over the same information, and the honest claim becomes 'probe-based dispatch
beats text-similarity dispatch'". The owner's choices (ADR-0016):

* **The classifier is a soft vote.** A program's score is the fraction of its
  preconditions that hold (`library.soft_vote_score`), read from the same
  `evaluate_preconditions` results arm 3 reads `.ok` from. Arm 3 is this vote at a
  threshold of 1.0, so the only thing that differs between the two arms is whether
  every probe must agree.
* **The threshold maximises tune-set accuracy** (`learn_soft_threshold`): the number
  of correct decisions -- firing the right variant, or abstaining where nothing is
  correct -- over outcomes collected on the tune seeds, ties going to the higher,
  stricter threshold.

This module owns three things: collecting 2b's outcomes on real sandboxes
(`soft_vote_outcomes`), learning the threshold from them, and the pre-registered
rule that decides whether Claim 2 must be restated (`claim2_verdict`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel

from ..library import Library
from ..signatures import StateFingerprint
from ..tasks.faults import build_sandbox
from ..tasks.registry import ambiguous_intents
from .coverage import (
    MatchedComparison,
    OperatingPoint,
    PairOutcome,
    matched_comparison,
)
from .report import EQUIVALENCE_MARGIN, TOST_ALPHA, Equivalence, tost_equivalence

NEVER_FIRES = math.nextafter(1.0, math.inf)
"""A threshold above every possible soft-vote score (scores are fractions in [0, 1]), so
the vote abstains everywhere. Always a candidate: if abstaining is the most accurate
decision on the tune set, that is what the learned threshold must say."""

CLAIM2_AS_REGISTERED = (
    "at matched dispatch coverage, executable-precondition dispatch mis-fires less often "
    "than text-similarity dispatch"
)
CLAIM2_RESTATED = "probe-based dispatch beats text-similarity dispatch"
"""Issue #7's restatement, required when the soft vote ties arm 3: the probes carry the
information, and requiring every one of them to hold adds nothing measurable."""


def soft_vote_outcomes(
    library: Library, faults: Sequence[str], seeds: Sequence[int]
) -> list[PairOutcome]:
    """Arm 2b's top choice and score on real sandboxes, before any threshold.

    For every (fault, seed) two sandboxes are built: the fault injected at that seed, a
    **positive** whose label is the intent's ground-truth variant for the observed
    state, and the clean sandbox at that seed, a **negative** where any fire is wrong.
    Each pair's outcome is `library.rank_soft`'s first element -- the program the vote
    would fire at any threshold it clears -- with its score, so `coverage.sweep` traces
    2b's whole curve and `learn_soft_threshold` picks one point from it.

    The soft vote reads the environment, not the request text, so every outcome is
    recorded in the uninformed regime, the one the primary claim is measured in.
    Every sandbox is destroyed before the next is built.
    """
    intents = {intent.fault: intent for intent in ambiguous_intents()}
    outcomes: list[PairOutcome] = []
    for fault in faults:
        intent = intents.get(fault)
        if intent is None:
            raise ValueError(f"fault {fault!r} has no ambiguous intent, so it has no labels")
        for seed in seeds:
            for injected in ([fault], []):
                box = build_sandbox(seed, injected)
                try:
                    correct = (
                        intent.correct_variant(StateFingerprint.observe(box)) if injected else None
                    )
                    ranked = library.rank_soft(box)
                finally:
                    box.destroy()
                top = ranked[0] if ranked else None
                outcomes.append(
                    PairOutcome(
                        correct_variant=correct.id if correct is not None else None,
                        fired_variant=top.program.variant if top is not None else None,
                        score=top.score if top is not None else None,
                        informed=False,
                    )
                )
    return outcomes


def _decision(outcome: PairOutcome, threshold: float) -> str | None:
    """The variant the vote fires on `outcome` at `threshold`, or `None` to abstain."""
    clears = outcome.score is not None and outcome.score >= threshold
    return outcome.fired_variant if clears else None


def _correct_decisions(outcomes: Sequence[PairOutcome], threshold: float) -> int:
    """How many outcomes the vote decides correctly at `threshold`.

    A decision is correct when it equals the label, so abstaining on a negative counts
    and abstaining on a positive does not. The floor is inclusive, as in
    `coverage.operating_point`, so the accuracy here and the curve there agree.
    """
    return sum(_decision(outcome, threshold) == outcome.correct_variant for outcome in outcomes)


def learn_soft_threshold(outcomes: Sequence[PairOutcome]) -> float:
    """The threshold that makes the most correct decisions; ties go to the higher one.

    Candidates are every distinct score an outcome fired at -- the points where the
    decision set changes -- plus `NEVER_FIRES`, so abstaining everywhere is always on
    the table. Ties go to the stricter threshold: between two equally accurate floors,
    the one that fires less is the one less likely to have been fitted to the tune set's
    luck. Refuses an empty input, which has no accuracy to maximise.
    """
    if not outcomes:
        raise ValueError("no outcomes to learn a threshold from; collect them on the tune seeds")
    candidates = {
        outcome.score
        for outcome in outcomes
        if outcome.fired_variant is not None and outcome.score is not None
    }
    candidates.add(NEVER_FIRES)
    return max(
        candidates, key=lambda threshold: (_correct_decisions(outcomes, threshold), threshold)
    )


class Claim2Verdict(BaseModel):
    """Whether the soft vote ties arm 3 at matched coverage, and the claim that follows."""

    matched: MatchedComparison
    """2b's point nearest arm 3's coverage (in the `arm2` field) against arm 3's point."""
    equivalence: Equivalence | None
    """The TOST on the two per-fire mismatch rates; `None` when either fired nothing."""
    collapsed: bool
    """2b's matched point is the hard rule itself (threshold at or above 1.0), so it makes
    arm 3's decisions exactly and the TOST cannot say anything about a *soft* rule."""
    restate: bool
    claim: str
    reason: str


def claim2_verdict(
    soft_curve: Sequence[OperatingPoint],
    arm3: OperatingPoint,
    *,
    margin: float = EQUIVALENCE_MARGIN,
    alpha: float = TOST_ALPHA,
) -> Claim2Verdict:
    """The pre-registered test for restating Claim 2 (issue #7, ADR-0016).

    2b's curve is matched to arm 3's coverage by the primary metric's own rule
    (`coverage.matched_comparison`: nearest coverage, ties to the lower), and the two
    per-fire mismatch rates are compared by the same TOST the spec pre-registers for
    success rates, at the same margin and alpha. **Equivalent** means the hard
    conjunction measurably adds nothing over a soft vote on the same probes, so Claim 2
    is restated as `CLAIM2_RESTATED` -- unless the matched 2b point *is* the hard rule
    (threshold at or above 1.0), where the two arms make identical decisions and
    equivalence is a tautology: that case is `collapsed` and keeps the registered
    wording, because the data chose the hard conjunction rather than refuting it.
    Anything else -- arm 3 lower, 2b lower, or an interval too wide to show
    equivalence -- keeps the registered wording; whether the registered claim then
    *holds* against arm 2 is the primary comparison's question, not this one's.
    """
    matched = matched_comparison(soft_curve, arm3)
    equivalence = tost_equivalence(
        matched.arm2.mismatch,
        arm3.mismatch,
        margin=margin,
        alpha=alpha,
        quantity="per-fire mismatch rates",
    )
    threshold = matched.arm2.threshold
    collapsed = threshold is not None and threshold >= 1.0
    if collapsed:
        reason = (
            "at arm 3's coverage the soft vote's matched point is the hard rule itself "
            "(threshold >= 1.0), so it makes arm 3's decisions and cannot show that requiring "
            "every probe adds nothing; the registered claim keeps its wording"
        )
    elif equivalence is None:
        reason = "one of the two arms fired nothing at matched coverage, so there is no test"
    else:
        reason = equivalence.reason
    restate = not collapsed and equivalence is not None and equivalence.equivalent
    return Claim2Verdict(
        matched=matched,
        equivalence=equivalence,
        collapsed=collapsed,
        restate=restate,
        claim=CLAIM2_RESTATED if restate else CLAIM2_AS_REGISTERED,
        reason=reason,
    )
