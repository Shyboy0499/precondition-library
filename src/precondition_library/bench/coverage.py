"""The primary metric: mismatch against coverage over labelled dispatch pairs (issue #5).

Spec §7 item 1 pre-registers the comparison as "at matched dispatch coverage, the
executable-precondition dispatcher mis-fires less". This module is the machinery for it,
and it takes **dispatch outcomes**, not dispatchers: one `PairOutcome` per labelled pair,
saying what fired (if anything) and at what score. How an outcome was produced -- a
compiled library, hand-written gold, or a synthetic test -- is the caller's business, so
the arithmetic here can be exercised before a compiled library exists and cannot come to
depend on one dispatcher's internals.

**The two arms are not swept the same way, because they are not the same kind of
dispatcher** (ADR-0008). Arm 2 ranks candidates by a similarity score and fires the top
one when its score clears a threshold (`Library.match_semantic`, inclusive floor), so its
threshold is swept over every distinct score it produced and it traces a curve. Arm 3 has
no score: it fires the most specific program whose preconditions all hold, or nothing
(`Library.match_preconditions`). It is **one operating point**, and the pre-registered
coverage point is arm 3's own coverage, so no coverage value had to be picked.

**Definitions, fixed before any data:**

* *coverage* -- fires / pairs. Negative pairs (no resolution is correct) are in the
  denominator: a dispatcher that fires on them is covering states it should not touch.
* *mismatch* -- wrong fires / fires, where a fire is wrong when the fired variant is not
  the pair's correct one, **including any fire on a negative pair**. Per fire, because
  the spec's mis-fire is "a program that runs, claims success, and did not"; a per-pair
  rate would fold coverage back in and reward a dispatcher for rarely firing.
* *matched coverage* -- arm 2's operating point whose coverage is nearest arm 3's, a tie
  going to the **lower** coverage. Exact matching is generally impossible with discrete
  scores, so the gap is reported beside the comparison; and the tie goes the way that
  usually lowers arm 2's mismatch, so the rule cannot favour arm 3.

**Regimes are never pooled.** Every function refuses outcomes from both request
channels, for the reason `bench.textcontrol` gives: the uninformed channel is chance by
construction and the informed one is the boundary condition, and an average describes
neither (ADR-0004). Intents within one regime may be pooled, as ADR-0003 allows.

**An arm that cannot lose makes the comparison vacuous** (the #5 design comment). Until
arm 3's programs are compiled, they are hand-written and agree with the intents'
`decided_by` rules -- which are what label the pairs -- so arm 3 answers every pair
correctly by construction. `vacuous_reason` says so, and a report must print it instead
of the comparison.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction

from pydantic import BaseModel

from ..library import DEFAULT_RERANK_K
from ..similarity import Similarity
from .pairs import LabelledPair
from .report import Interval, Rate, wilson_interval


class PairOutcome(BaseModel):
    """What one dispatcher did on one labelled pair."""

    correct_variant: str | None
    """The pair's label; `None` for a negative pair, where every fire is wrong."""
    fired_variant: str | None
    """The variant the dispatcher would fire, before any threshold. `None` means nothing
    was eligible at all (arm 3 found no program whose preconditions held)."""
    score: float | None
    """Arm 2's score for `fired_variant`; `None` for a dispatcher with no score (arm 3)."""
    informed: bool
    """Which request channel the pair's text came through, so regimes cannot be pooled."""


class OperatingPoint(BaseModel):
    """One (threshold, coverage, mismatch) point, with every numerator and denominator."""

    threshold: float | None
    """The inclusive floor this point fires at; `None` for a dispatcher with no score."""
    coverage: Rate
    mismatch: Rate
    """Wrong fires over fires. Its rate is `None` when nothing fired: no fires, no rate."""
    mismatch_interval: Interval | None
    """The 95% Wilson interval on `mismatch`; `None` when nothing fired."""


def _require_one_regime(outcomes: Sequence[PairOutcome]) -> None:
    if len({outcome.informed for outcome in outcomes}) > 1:
        raise ValueError(
            "outcomes span both request regimes; the informed and uninformed channels answer "
            "different questions and are never pooled (ADR-0004) -- pass one regime at a time"
        )


def _fires(outcome: PairOutcome, threshold: float | None) -> bool:
    if outcome.fired_variant is None:
        return False
    if threshold is None:
        return True
    return outcome.score is not None and outcome.score >= threshold


def operating_point(
    outcomes: Sequence[PairOutcome], threshold: float | None = None
) -> OperatingPoint:
    """Coverage and per-fire mismatch at one threshold (`None`: fire whenever eligible)."""
    _require_one_regime(outcomes)
    fired = [outcome for outcome in outcomes if _fires(outcome, threshold)]
    wrong = sum(outcome.fired_variant != outcome.correct_variant for outcome in fired)
    return OperatingPoint(
        threshold=threshold,
        coverage=Rate(numerator=len(fired), denominator=len(outcomes)),
        mismatch=Rate(numerator=wrong, denominator=len(fired)),
        mismatch_interval=wilson_interval(wrong, len(fired)),
    )


def sweep(outcomes: Sequence[PairOutcome]) -> list[OperatingPoint]:
    """Arm 2's curve: one point per distinct score, from strictest to most permissive.

    Every distinct score is a threshold at which the fired set changes, so the curve has
    every achievable operating point and no interpolated one. A threshold above the
    highest score -- coverage 0 -- is not listed: it fires nothing and has no mismatch.
    """
    _require_one_regime(outcomes)
    if any(o.fired_variant is not None and o.score is None for o in outcomes):
        raise ValueError(
            "a fired outcome has no score, so there is no threshold to sweep; a dispatcher "
            "without a score is one operating point (`operating_point`), not a curve"
        )
    thresholds = sorted(
        {o.score for o in outcomes if o.fired_variant is not None and o.score is not None},
        reverse=True,
    )
    return [operating_point(outcomes, threshold) for threshold in thresholds]


class MatchedComparison(BaseModel):
    """Arm 2 against arm 3 at arm 3's coverage (spec §7 item 1, ADR-0008)."""

    arm3: OperatingPoint
    arm2: OperatingPoint
    coverage_gap: float
    """Arm 2's coverage minus arm 3's. Exact matching is rarely possible; this says how far
    from it the comparison is."""
    mismatch_difference: float | None
    """Arm 2's mismatch minus arm 3's; positive means arm 3 mis-fires less. `None` when
    either arm fired nothing."""


def matched_comparison(
    arm2_curve: Sequence[OperatingPoint], arm3: OperatingPoint
) -> MatchedComparison:
    """Pick arm 2's point nearest arm 3's coverage; a tie goes to the lower coverage.

    Distances are compared as exact fractions, so a genuine tie is decided by the rule
    rather than by which float subtraction happened to round down.
    """
    target = arm3.coverage.value
    if target is None:
        raise ValueError("arm 3's operating point has no pairs, so it has no coverage to match")
    candidates = [point for point in arm2_curve if point.coverage.denominator > 0]
    if not candidates:
        raise ValueError("arm 2's curve is empty: it fired on no pair at any threshold")
    exact_target = Fraction(arm3.coverage.numerator, arm3.coverage.denominator)

    def distance(point: OperatingPoint) -> tuple[Fraction, Fraction]:
        coverage = Fraction(point.coverage.numerator, point.coverage.denominator)
        return abs(coverage - exact_target), coverage

    chosen = min(candidates, key=distance)
    arm2_mismatch, arm3_mismatch = chosen.mismatch.value, arm3.mismatch.value
    return MatchedComparison(
        arm3=arm3,
        arm2=chosen,
        coverage_gap=(chosen.coverage.value or 0.0) - target,
        mismatch_difference=(
            arm2_mismatch - arm3_mismatch
            if arm2_mismatch is not None and arm3_mismatch is not None
            else None
        ),
    )


def vacuous_reason(arm3_outcomes: Sequence[PairOutcome]) -> str | None:
    """Why the comparison is vacuous, or `None` when it is an experiment.

    It is vacuous when arm 3 decides **every** pair correctly: the correct variant on each
    positive pair and no fire on each negative. That is what hand-written programs that
    agree with the labelling rules do by construction, so the comparison would report
    that the answer key beats a dispatcher, not that preconditions beat text.
    """
    _require_one_regime(arm3_outcomes)
    if not arm3_outcomes:
        return None
    if all(o.fired_variant == o.correct_variant for o in arm3_outcomes):
        return (
            f"arm 3 decides all {len(arm3_outcomes)} pairs correctly, so it is the labelling "
            f"rule rather than a dispatcher: the comparison needs fallible (compiled) programs"
        )
    return None


def detectable_difference(
    fires_a: int,
    fires_b: int,
    *,
    base_rate: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float | None:
    """The smallest mismatch difference two arms' fires can detect (spec §7 item 3).

    Normal approximation for two independent proportions at a shared `base_rate`, with a
    two-sided `alpha`: `(z(1 - alpha/2) + z(power)) * sqrt(p(1-p)(1/n_a + 1/n_b))`. The
    defaults are the conventional ones and are recorded in ADR-0008 as defaults, not as a
    pre-registered alpha for the directional claim. `None` when either arm fired nothing.
    """
    if not 0.0 < alpha < 1.0 or not 0.0 < power < 1.0:
        raise ValueError(f"alpha and power must be in (0, 1), got {alpha} and {power}")
    if not 0.0 <= base_rate <= 1.0:
        raise ValueError(f"base_rate must be in [0, 1], got {base_rate}")
    if fires_a <= 0 or fires_b <= 0:
        return None
    normal = statistics.NormalDist()
    z = normal.inv_cdf(1.0 - alpha / 2.0) + normal.inv_cdf(power)
    return z * math.sqrt(base_rate * (1.0 - base_rate) * (1.0 / fires_a + 1.0 / fires_b))


def arm2_outcomes(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
    *,
    reranker: Similarity | None = None,
    rerank_k: int = DEFAULT_RERANK_K,
) -> list[PairOutcome]:
    """Arm 2 on labelled pairs: the top-scoring candidate and its score, before a threshold.

    The same crossing `bench.similarity_probe` measures arm 2 with -- the pair's request
    text against each candidate's program text -- and the same tie-break as
    `Library.match_semantic` (score, then id), so a tie still fires one program.

    With a `reranker`, as in `Library.match_semantic` (ADR-0011): `scorer` retrieves the
    top `rerank_k`, the reranker rescores them, and the reranker's score is the one the
    sweep thresholds.
    """
    outcomes: list[PairOutcome] = []
    for pair in pairs:
        ranked = sorted(
            ((scorer(pair.task_text, text), variant) for variant, text in candidates.items()),
            key=lambda item: (-item[0], item[1]),
        )
        if reranker is not None:
            ranked = sorted(
                (
                    (reranker(pair.task_text, candidates[variant]), variant)
                    for _, variant in ranked[:rerank_k]
                ),
                key=lambda item: (-item[0], item[1]),
            )
        top = ranked[0] if ranked else None
        outcomes.append(
            PairOutcome(
                correct_variant=pair.correct_variant,
                fired_variant=top[1] if top is not None else None,
                score=top[0] if top is not None else None,
                informed=pair.informed,
            )
        )
    return outcomes


def arm3_outcomes(
    pairs: Sequence[LabelledPair], decide: Callable[[LabelledPair], str | None]
) -> list[PairOutcome]:
    """Arm 3 on labelled pairs, from a caller-supplied decision.

    `decide` returns the variant arm 3 fires for the pair's state, or `None`. With a
    compiled library that is `match_preconditions` over a built sandbox; the arithmetic
    here does not care, which is what lets the guard be exercised on gold today.
    """
    return [
        PairOutcome(
            correct_variant=pair.correct_variant,
            fired_variant=decide(pair),
            score=None,
            informed=pair.informed,
        )
        for pair in pairs
    ]
