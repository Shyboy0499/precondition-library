"""Study 2's registered statistics (`docs/preregistration/refusal-population.md`, §7 and §9).

Pure functions over who fired on which evaluation case, so each can be checked by hand. The
study's runner (mining, building, deciding) is a separate module; this one only computes.

* **A case** is a conflicted case nothing can express (`inexpressible`), a `clean` one, or
  another conflicted one (`other`, reported but in no hypothesis).
* **A dispatcher's decisions** map each case index to whether it fired and whether that fire was
  right. A build is one such map, and a control is one too, the same for every build.
* `fire_rate` is §2's `f`: fires over inexpressible cases. `clean_right_rate` is right fires over
  clean cases.
* H1 and H2 are `mean over builds of f(control) - f(build)`, H3 is
  `mean f(configuration 0) - mean f(configuration R)`, and H4 is
  `mean right(R) - mean right(0)` on clean cases.
* `two_level_bootstrap` gives each a 95% interval. Each of `BOOTSTRAP_RESAMPLES` resamples
  draws the evaluation repositories with replacement, so the cases are clustered by repository,
  and each configuration's builds with replacement, independently.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from .report import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, Interval

Kind = Literal["inexpressible", "clean", "other"]

H4_MARGIN = 0.10
"""§2's non-inferiority margin: configuration R may lose at most this much on clean cases."""

MIN_VALID_BUILDS = 8
"""§8: fewer valid builds than this in either configuration makes the study underpowered."""


class Case(BaseModel):
    index: int
    repo: str
    kind: Kind


class Fire(BaseModel):
    fired: bool
    right: bool


Decisions = Mapping[int, Fire]
"""One dispatcher's decision on every evaluation case, by case index."""


def fire_rate(decisions: Decisions, cases: Sequence[Case]) -> float | None:
    """§2's `f`: the share of inexpressible cases fired on, counting a case drawn twice twice."""
    pool = [case for case in cases if case.kind == "inexpressible"]
    if not pool:
        return None
    return sum(decisions[case.index].fired for case in pool) / len(pool)


def clean_right_rate(decisions: Decisions, cases: Sequence[Case]) -> float | None:
    """Right fires over clean cases."""
    pool = [case for case in cases if case.kind == "clean"]
    if not pool:
        return None
    return sum(decisions[case.index].right for case in pool) / len(pool)


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present or len(present) != len(values):
        return None
    return sum(present) / len(present)


def against_control(
    builds: Sequence[Decisions], control: Decisions, cases: Sequence[Case]
) -> float | None:
    """H1's and H2's statistic: the mean over builds of `f(control) - f(build)`."""
    reference = fire_rate(control, cases)
    if reference is None:
        return None
    return _mean([_diff(reference, fire_rate(build, cases)) for build in builds])


def _diff(left: float, right: float | None) -> float | None:
    return None if right is None else left - right


def between_configurations(
    zero: Sequence[Decisions], refusal: Sequence[Decisions], cases: Sequence[Case]
) -> float | None:
    """H3's statistic: `mean f(configuration 0) - mean f(configuration R)`."""
    left = _mean([fire_rate(build, cases) for build in zero])
    right = _mean([fire_rate(build, cases) for build in refusal])
    return None if left is None or right is None else left - right


def clean_cost(
    zero: Sequence[Decisions], refusal: Sequence[Decisions], cases: Sequence[Case]
) -> float | None:
    """H4's statistic: `mean right(R) - mean right(0)` on clean cases; negative is a cost."""
    left = _mean([clean_right_rate(build, cases) for build in refusal])
    right = _mean([clean_right_rate(build, cases) for build in zero])
    return None if left is None or right is None else left - right


class Estimate(BaseModel):
    statistic: float | None
    interval: Interval | None
    """`None` when more than half the resamples left the statistic undefined."""
    resamples: int
    skipped: int


def two_level_bootstrap(
    cases: Sequence[Case],
    groups: Sequence[Sequence[Decisions]],
    statistic: Callable[[Sequence[Case], Sequence[Sequence[Decisions]]], float | None],
) -> Estimate:
    """`statistic` on the data, and its 2.5th and 97.5th percentiles over resamples.

    Each resample draws the repositories with replacement (every case of a drawn repository,
    once per draw) and, independently, each group of builds with replacement. `groups` is the
    builds the statistic compares: one configuration's for H1 and H2, both for H3 and H4.
    """
    point = statistic(cases, groups)
    repos = sorted({case.repo for case in cases})
    by_repo = {repo: [case for case in cases if case.repo == repo] for repo in repos}
    rng = random.Random(BOOTSTRAP_SEED)
    values: list[float] = []
    skipped = 0
    for _ in range(BOOTSTRAP_RESAMPLES):
        drawn = [case for repo in rng.choices(repos, k=len(repos)) for case in by_repo[repo]]
        resampled = [rng.choices(list(group), k=len(group)) for group in groups]
        value = statistic(drawn, resampled)
        if value is None:
            skipped += 1
        else:
            values.append(value)
    if len(values) < BOOTSTRAP_RESAMPLES // 2:
        return Estimate(statistic=point, interval=None, resamples=len(values), skipped=skipped)
    values.sort()
    interval = Interval(
        low=values[math.floor(0.025 * (len(values) - 1))],
        high=values[math.ceil(0.975 * (len(values) - 1))],
    )
    return Estimate(statistic=point, interval=interval, resamples=len(values), skipped=skipped)


class Hypotheses(BaseModel):
    h1: Estimate
    h2: Estimate
    h3: Estimate
    h4: Estimate


def estimate(
    cases: Sequence[Case],
    zero: Sequence[Decisions],
    refusal: Sequence[Decisions],
    control_zero: Decisions,
    control_refusal: Decisions,
) -> Hypotheses:
    """Every hypothesis's statistic and interval (§7)."""
    return Hypotheses(
        h1=two_level_bootstrap(
            cases, [refusal], lambda c, g: against_control(g[0], control_refusal, c)
        ),
        h2=two_level_bootstrap(cases, [zero], lambda c, g: against_control(g[0], control_zero, c)),
        h3=two_level_bootstrap(
            cases, [zero, refusal], lambda c, g: between_configurations(g[0], g[1], c)
        ),
        h4=two_level_bootstrap(cases, [zero, refusal], lambda c, g: clean_cost(g[0], g[1], c)),
    )


class Decision(BaseModel):
    rule: str
    outcome: str


def _above(estimate: Estimate, bound: float) -> bool:
    return estimate.interval is not None and estimate.interval.low > bound


def decide(
    hypotheses: Hypotheses,
    *,
    underpowered: bool,
    zero: Sequence[Decisions],
    refusal: Sequence[Decisions],
    cases: Sequence[Case],
) -> list[Decision]:
    """§9's rules, in order. Rule 1 stops the rest; rule 2 removes a configuration's tests."""
    if underpowered:
        return [Decision(rule="1 power", outcome="underpowered: figures reported, nothing decided")]
    decisions = [Decision(rule="1 power", outcome="powered")]

    def silent(builds: Sequence[Decisions]) -> bool:
        return not any(build[case.index].fired for build in builds for case in cases)

    zero_silent, refusal_silent = silent(zero), silent(refusal)
    silent_ones = [name for name, quiet in (("0", zero_silent), ("R", refusal_silent)) if quiet]
    decisions.append(
        Decision(
            rule="2 applicability",
            outcome=(
                f"configuration {' and '.join(silent_ones)} fires on no case; its hypotheses "
                "are not tested"
                if silent_ones
                else "both configurations fire"
            ),
        )
    )
    if refusal_silent:
        decisions.append(Decision(rule="3 H1", outcome="not tested"))
    else:
        decisions.append(
            Decision(
                rule="3 H1",
                outcome="supported: lower bound above 0"
                if _above(hypotheses.h1, 0.0)
                else "not supported: executing checks does not decline better than a state "
                "reader given the same evidence",
            )
        )
    decisions.append(
        Decision(
            rule="4 H2",
            outcome="not tested"
            if zero_silent
            else "supported: lower bound above 0"
            if _above(hypotheses.h2, 0.0)
            else "not supported",
        )
    )
    if zero_silent or refusal_silent:
        decisions.append(Decision(rule="5 H3 and H4", outcome="not tested"))
    else:
        h3 = _above(hypotheses.h3, 0.0)
        h4 = _above(hypotheses.h4, -H4_MARGIN)
        outcome = (
            "H3 supported, H4 fails: refusal-tested admission buys declining at the cost of "
            "clean merges"
            if h3 and not h4
            else f"H3 {'supported' if h3 else 'not supported'}, H4 {'holds' if h4 else 'fails'}"
        )
        decisions.append(Decision(rule="5 H3 and H4", outcome=outcome))
    return decisions


def spread(rates: Sequence[float]) -> dict[str, float]:
    """§7's reported spread of `f` across one configuration's builds: SD, range and IQR."""
    ordered = sorted(rates)
    n = len(ordered)
    mean = sum(ordered) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in ordered) / (n - 1)) if n > 1 else 0.0

    def quantile(q: float) -> float:
        position = q * (n - 1)
        low, high = math.floor(position), math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "mean": mean,
        "sd": sd,
        "min": ordered[0],
        "max": ordered[-1],
        "iqr": quantile(0.75) - quantile(0.25),
    }
