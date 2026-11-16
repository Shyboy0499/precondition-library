"""The registered tests of the real-merge study (§7 and Amendment 1 of the registration).

Pure functions over per-case outcomes, so each can be checked by hand:

* `cluster_bootstrap` resamples repositories, not cases, with the project's fixed resample count
  and seed (`report.BOOTSTRAP_RESAMPLES`, `report.BOOTSTRAP_SEED`);
* `mcnemar` is the exact two-sided test on discordant pairs;
* `matched_difference` is H1's and H2's statistic, the matched dispatcher's mismatch minus arm
  3's at arm 3's coverage;
* `refusal_difference` is H3's, the control's fire rate on inexpressible conflicted cases minus
  arm 3's, the control read at its matched threshold;
* `decide` applies §9's rules in order.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

from pydantic import BaseModel

from precondition_library.experiment.coverage import (
    PairOutcome,
    _fires,
    matched_comparison,
    operating_point,
    sweep,
)
from precondition_library.experiment.report import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    Interval,
    wilson_interval,
)


class Clustered(BaseModel):
    """One case's outcomes for the dispatchers being compared, and the repository it is from."""

    repo: str
    arm3: PairOutcome
    other: PairOutcome
    inexpressible_conflict: bool
    """A conflicted case whose acceptable set is empty: refusing is the only right decision."""


def matched_difference(rows: Sequence[Clustered]) -> float | None:
    """`other`'s mismatch minus arm 3's, `other` swept to arm 3's coverage.

    Positive favours arm 3.
    """
    arm3 = [row.arm3 for row in rows]
    other = [row.other for row in rows]
    point = operating_point(arm3)
    if not point.coverage.numerator or not any(o.fired_variant for o in other):
        return None
    return matched_comparison(sweep(other), point).mismatch_difference


def _threshold(rows: Sequence[Clustered]) -> float | None:
    point = operating_point([row.arm3 for row in rows])
    if not point.coverage.numerator or not any(row.other.fired_variant for row in rows):
        return None
    return matched_comparison(sweep([row.other for row in rows]), point).arm2.threshold


def refusal_difference(rows: Sequence[Clustered]) -> float | None:
    """`other`'s fire rate on inexpressible conflicts minus arm 3's; positive favours arm 3."""
    threshold = _threshold(rows)
    cases = [row for row in rows if row.inexpressible_conflict]
    if threshold is None or not cases:
        return None
    other = sum(_fires(row.other, threshold) for row in cases)
    arm3 = sum(_fires(row.arm3, None) for row in cases)
    return (other - arm3) / len(cases)


class Inference(BaseModel):
    statistic: float | None
    interval: Interval | None
    """The 95% repository-clustered bootstrap interval; `None` if too few resamples were defined."""
    discordant: tuple[int, int]
    """McNemar's (b, c): cases where only arm 3 is right, and where only the other is."""
    p_value: float | None
    resamples: int
    skipped: int


def cluster_bootstrap(
    rows: Sequence[Clustered], statistic: Callable[[Sequence[Clustered]], float | None]
) -> tuple[Interval | None, int]:
    """The 2.5th and 97.5th percentiles of `statistic` over repository resamples, and skips."""
    repos = sorted({row.repo for row in rows})
    by_repo = {repo: [row for row in rows if row.repo == repo] for repo in repos}
    rng = random.Random(BOOTSTRAP_SEED)
    values: list[float] = []
    skipped = 0
    for _ in range(BOOTSTRAP_RESAMPLES):
        drawn = [row for repo in rng.choices(repos, k=len(repos)) for row in by_repo[repo]]
        value = statistic(drawn)
        if value is None:
            skipped += 1
        else:
            values.append(value)
    if len(values) < BOOTSTRAP_RESAMPLES // 2:
        return None, skipped
    values.sort()
    low = values[math.floor(0.025 * (len(values) - 1))]
    high = values[math.ceil(0.975 * (len(values) - 1))]
    return Interval(low=low, high=high), skipped


def mcnemar(b: int, c: int) -> float | None:
    """The exact two-sided McNemar p-value on `b` and `c` discordant pairs."""
    n = b + c
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _right(outcome: PairOutcome) -> bool:
    return outcome.fired_variant is not None and outcome.fire_is_right(outcome.fired_variant)


def matched_test(rows: Sequence[Clustered]) -> Inference:
    """H1 or H2: the matched mismatch difference, its interval, and McNemar on joint fires."""
    threshold = _threshold(rows)
    b = c = 0
    if threshold is not None:
        for row in rows:
            if _fires(row.arm3, None) and _fires(row.other, threshold):
                b += _right(row.arm3) and not _right(row.other)
                c += _right(row.other) and not _right(row.arm3)
    interval, skipped = cluster_bootstrap(rows, matched_difference)
    return Inference(
        statistic=matched_difference(rows),
        interval=interval,
        discordant=(b, c),
        p_value=mcnemar(b, c),
        resamples=BOOTSTRAP_RESAMPLES,
        skipped=skipped,
    )


def refusal_test(rows: Sequence[Clustered]) -> Inference:
    """H3: on inexpressible conflicts, McNemar's (b, c) are where only arm 3 refuses, and only
    the control does."""
    threshold = _threshold(rows)
    b = c = 0
    if threshold is not None:
        for row in rows:
            if row.inexpressible_conflict:
                arm3_fires, other_fires = _fires(row.arm3, None), _fires(row.other, threshold)
                b += other_fires and not arm3_fires
                c += arm3_fires and not other_fires
    interval, skipped = cluster_bootstrap(rows, refusal_difference)
    return Inference(
        statistic=refusal_difference(rows),
        interval=interval,
        discordant=(b, c),
        p_value=mcnemar(b, c),
        resamples=BOOTSTRAP_RESAMPLES,
        skipped=skipped,
    )


class Decision(BaseModel):
    rule: str
    outcome: str


def decide(
    arm3: Sequence[PairOutcome], h1: Inference, h2: Inference, *, underpowered: bool
) -> list[Decision]:
    """§9's rules, in order, for one replicate (rule 1 as Amendment 1 words it)."""
    fires = sum(o.fired_variant is not None for o in arm3)
    if fires < 20:
        return [Decision(rule="1 applicability", outcome=f"not tested: arm 3 fired {fires} < 20")]
    point = operating_point(arm3)
    wilson = wilson_interval(point.mismatch.numerator, point.mismatch.denominator)
    decisions = [
        Decision(rule="1 applicability", outcome=f"tested: arm 3 fired {fires}"),
        Decision(
            rule="2 arm 3's reliability",
            outcome=(
                "falsified: Wilson lower bound above 0.10"
                if wilson is not None and wilson.low > 0.10
                else "not falsified"
            ),
        ),
    ]
    for rule, test in (("3 against similarity (H1)", h1), ("4 against reading the state (H2)", h2)):
        if underpowered:
            outcome = "underpowered: reported, neither supported nor refuted"
        elif test.interval is None:
            outcome = "undefined: too few defined resamples"
        elif test.interval.low > 0:
            outcome = "supported: lower bound above 0"
        else:
            outcome = "not supported: lower bound at or below 0"
        decisions.append(Decision(rule=rule, outcome=outcome))
    return decisions
