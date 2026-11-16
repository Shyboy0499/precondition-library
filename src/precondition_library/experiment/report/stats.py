"""Rates, means and their intervals, and the equivalence test the report's wording rests on."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable

from pydantic import BaseModel

Z_95 = 1.96


"""The normal quantile for a 95% interval, the conventional rounded value."""


INVALID_RATE_ALARM = 0.10


"""Spec §7 item 9: above this, the run is re-run rather than analysed."""


SMALL_SAMPLE_N = 30


"""Below this, a rate is labelled as too small to read as a finding.

A reporting guard chosen by this module, not a pre-registered threshold -- the
pre-registration does not fix an episode count, because the episode loop is
underpowered at any N it runs. The guard exists so that a rate over three
episodes cannot print as though it were a result.
"""


class Interval(BaseModel):
    """A closed confidence interval; the intervals in this module are 95% Wilson."""

    low: float
    high: float


class Rate(BaseModel):
    """A proportion that always travels with the counts behind it."""

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        """The proportion, or None when the denominator is zero.

        None rather than 0.0 is deliberate: 0/0 has no value, and returning 0.0
        would make an empty group look like a rate of zero.
        """
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def interval(self) -> Interval | None:
        """The 95% Wilson interval, or None when there is nothing to estimate."""
        return wilson_interval(self.numerator, self.denominator)


class Mean(BaseModel):
    """An average that carries the number of observations it averaged."""

    n: int
    value: float | None


EQUIVALENCE_MARGIN = 0.10


"""The pre-registered equivalence margin, in success-rate proportion points.

Registering the margin *before* data exists is the point of a TOST: one chosen after
seeing the interval can be widened until equivalence passes (spec §7 item 10).
"""


TOST_ALPHA = 0.05


"""The per-test alpha. Two one-sided tests at this level give a 90% interval."""


class Equivalence(BaseModel):
    """A two-one-sided-tests verdict on two arms' success rates.

    Carries the margin and alpha it ran at, because an equivalence claim without them
    says nothing: the same data is equivalent at 20pp and not at 5pp.

    `reason` distinguishes *why* equivalence did not pass, which the two failures are
    easily confused for. An interval too wide to fit inside the margin is an
    underpowered run, not evidence that the arms differ; an interval lying wholly
    outside the margin is evidence they do. Reporting both as "not equivalent" would
    let a thin sample read as a finding.
    """

    margin: float
    alpha: float
    difference: float
    interval: Interval
    p_lower: float
    p_upper: float
    equivalent: bool
    reason: str


def _phi(z: float) -> float:
    """The standard normal CDF, from the stdlib -- no SciPy for one function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _adjusted_variance(rate: Rate, z: float) -> float:
    """The Agresti-Coull adjusted variance of a proportion, over its denominator.

    The raw Wald variance is `p(1-p)/n`, which is **zero** whenever a rate is 0% or
    100% -- so a single episode scoring 1/1 against 1/1 would give a zero-width
    interval and be declared equivalent to anything. That is the same unearned upgrade
    from "no evidence of a difference" to "no difference" that this test exists to
    prevent, arriving through the arithmetic rather than the prose. Adding the
    adjustment's pseudo-counts keeps the variance positive at the boundary, so a thin
    sample reports that it is underpowered instead.
    """
    successes = rate.numerator
    total = rate.denominator
    adjusted_n = total + z * z
    adjusted_p = (successes + z * z / 2.0) / adjusted_n
    return adjusted_p * (1.0 - adjusted_p) / adjusted_n


def tost_equivalence(
    first: Rate,
    second: Rate,
    *,
    margin: float = EQUIVALENCE_MARGIN,
    alpha: float = TOST_ALPHA,
    quantity: str = "success rates",
) -> Equivalence | None:
    """Whether two success rates are equivalent within `margin`, by TOST.

    The arithmetic holds for any two proportions; `quantity` names them in the reason, so a
    caller comparing mismatch rates (`bench.soft_vote.claim2_verdict`) is not told about
    success rates.

    Two one-sided tests against the margin, which is the same as asking whether the
    (1-2*alpha) interval for the difference lies wholly inside +/- margin. `None` when
    either arm has no graded episode: an equivalence claim needs two rates, and 0/0 is
    not one.
    """
    first_rate, second_rate = first.value, second.value
    if first_rate is None or second_rate is None:
        return None

    z = statistics.NormalDist().inv_cdf(1.0 - alpha)
    difference = first_rate - second_rate
    variance = _adjusted_variance(first, z) + _adjusted_variance(second, z)
    standard_error = math.sqrt(variance)

    p_lower = _phi((difference - margin) / standard_error)
    p_upper = 1.0 - _phi((difference + margin) / standard_error)
    interval = Interval(low=difference - z * standard_error, high=difference + z * standard_error)
    equivalent = max(p_lower, p_upper) < alpha

    if equivalent:
        reason = (
            f"the {1 - 2 * alpha:.0%} interval for the difference lies inside "
            f"+/-{margin:.0%}, so the two {quantity} are equivalent at this margin"
        )
    elif interval.low > -margin or interval.high < margin:
        reason = (
            f"the {1 - 2 * alpha:.0%} interval lies outside +/-{margin:.0%}, so the arms "
            f"differ by more than the margin: not equivalent, and not merely underpowered"
        )
    else:
        reason = (
            f"the {1 - 2 * alpha:.0%} interval is wider than +/-{margin:.0%}, so this run is "
            f"underpowered to show equivalence either way -- which is not the same as showing "
            f"the arms differ"
        )

    return Equivalence(
        margin=margin,
        alpha=alpha,
        difference=difference,
        interval=interval,
        p_lower=p_lower,
        p_upper=p_upper,
        equivalent=equivalent,
        reason=reason,
    )


def success_rate_wording(
    first: Rate,
    second: Rate,
    *,
    margin: float = EQUIVALENCE_MARGIN,
    alpha: float = TOST_ALPHA,
) -> tuple[str, Equivalence | None]:
    """The words a report may use about two success rates, and the test behind them.

    Spec §7 item 10: "equal" is allowed only where the equivalence test passes;
    otherwise the text says "comparable". Returning the phrase rather than leaving the
    choice to whoever writes the prose, because the failure mode is a sentence that
    quietly upgrades "did not differ detectably" into "did not differ".
    """
    verdict = tost_equivalence(first, second, margin=margin, alpha=alpha)
    wording = (
        "equal success rate"
        if verdict is not None and verdict.equivalent
        else "comparable success rate"
    )
    return wording, verdict


def wilson_interval(successes: int, n: int, z: float = Z_95) -> Interval | None:
    """The Wilson score interval for a binomial proportion. None when n == 0.

    Wilson rather than the normal approximation because the counts here are
    small and the rates sit at 0 or 1, where the normal interval collapses to a
    zero-width interval at the boundary and reports certainty from two episodes.
    Wilson stays inside [0, 1] and does not collapse: 0/10 is [0.000, 0.278], not
    [0.000, 0.000].
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be between 0 and n={n}, got {successes}")
    if z <= 0:
        raise ValueError(f"z must be positive, got {z}")
    if n == 0:
        return None
    proportion = successes / n
    z_squared = z * z
    denominator = 1.0 + z_squared / n
    centre = (proportion + z_squared / (2 * n)) / denominator
    margin = (z / denominator) * (
        (proportion * (1 - proportion) / n + z_squared / (4 * n * n)) ** 0.5
    )
    # The interval always contains its point; at 0 and 1 the two terms cancel exactly,
    # and floating point can leave a bound a rounding error on the wrong side of it
    # (0/11's low came out above 0, 6/6's high below 1), which a plot's error bar
    # refuses. So the point bounds the interval, as it does mathematically.
    return Interval(
        low=max(0.0, min(proportion, centre - margin)),
        high=min(1.0, max(proportion, centre + margin)),
    )


def _mean(values: Iterable[int | float]) -> Mean:
    """The mean, carrying the count it was taken over; None for an empty group."""
    materialised = [float(value) for value in values]
    if not materialised:
        return Mean(n=0, value=None)
    return Mean(n=len(materialised), value=sum(materialised) / len(materialised))
