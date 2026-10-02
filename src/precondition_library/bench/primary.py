"""The primary metric's report: Figure 1, the matched comparison and the power statement.

`bench.coverage` holds the pre-registered arithmetic (issue #5, ADR-0008) -- `sweep`,
`operating_point`, `matched_comparison`, `vacuous_reason`, `detectable_difference` --
but nothing assembled it into the thing spec §7 promises a reader: arm 2's
mismatch-against-coverage curve with a Wilson interval at **every** operating point,
arm 3's single point marked as the pre-registered coverage point (Figure 1), the
comparison at that coverage, and the item-3 power statement. This module does that,
for **one regime at a time**, because the regimes are never pooled (ADR-0004).

The vacuity guard comes first. While arm 3 decides every pair correctly -- as
hand-written programs that agree with the labelling rules do by construction -- the
report states `vacuous_reason` **instead of** a comparison: the curve is still drawn,
because it describes arm 2, but no "arm 3 mis-fires less" sentence may be read off it.

Issue #7's dispatching baselines go on the same plane when they are supplied: a
scored one (2b's soft vote) as a curve, an unscored one (2c's intent key) as a point.
They are context for the comparison, never part of it.

Nothing here runs a dispatcher or builds a sandbox: it takes `PairOutcome`s, so it can
be exercised on synthetic outcomes now and on a compiled library's outcomes later.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel

from .coverage import (
    MatchedComparison,
    OperatingPoint,
    PairOutcome,
    detectable_difference,
    matched_comparison,
    operating_point,
    sweep,
    vacuous_reason,
)

CONSERVATIVE_BASE_RATE = 0.5
"""The mismatch rate at which a two-proportion test has the least power. The power
statement is always given here, so it cannot be flattered by a low observed rate, and
beside the observed pooled rate when that rate is informative (strictly in (0, 1))."""


class PowerStatement(BaseModel):
    """Spec §7 item 3: what difference the matched comparison could detect."""

    arm2_fires: int
    arm3_fires: int
    alpha: float
    power: float
    at_conservative_rate: float | None
    """The detectable difference at `CONSERVATIVE_BASE_RATE`; `None` if an arm fired nothing."""
    observed_rate: float | None
    """The two arms' pooled per-fire mismatch at matched coverage, when it is in (0, 1)."""
    at_observed_rate: float | None


class Dispatcher(BaseModel):
    """One dispatcher on the plane: a curve if it has a score, otherwise a point."""

    name: str
    points: list[OperatingPoint]
    scored: bool


class PrimaryReport(BaseModel):
    """Figure 1 and the sentences that may be read off it, for one request regime."""

    informed: bool
    pairs: int
    arm2: Dispatcher
    arm3: OperatingPoint
    """The pre-registered coverage point: arm 3's own coverage (ADR-0008)."""
    vacuous: str | None
    """Why no comparison may be stated, or `None` when it is an experiment."""
    matched: MatchedComparison | None
    """Arm 2's nearest point to arm 3's coverage; `None` when arm 2 never fired."""
    power: PowerStatement | None
    baselines: list[Dispatcher]


def _regime(outcomes: Sequence[PairOutcome]) -> bool:
    regimes = {outcome.informed for outcome in outcomes}
    if len(regimes) != 1:
        raise ValueError(
            "the primary report is one regime at a time (ADR-0004); pass the informed and "
            "uninformed outcomes separately"
        )
    return regimes.pop()


def _dispatcher(name: str, outcomes: Sequence[PairOutcome]) -> Dispatcher:
    scored = any(outcome.score is not None for outcome in outcomes)
    points = sweep(outcomes) if scored else [operating_point(outcomes)]
    return Dispatcher(name=name, points=points, scored=scored)


def _power(matched: MatchedComparison, *, alpha: float, power: float) -> PowerStatement:
    arm2_fires = matched.arm2.mismatch.denominator
    arm3_fires = matched.arm3.mismatch.denominator
    wrong = matched.arm2.mismatch.numerator + matched.arm3.mismatch.numerator
    fires = arm2_fires + arm3_fires
    observed = wrong / fires if fires else None
    informative = observed is not None and 0.0 < observed < 1.0
    return PowerStatement(
        arm2_fires=arm2_fires,
        arm3_fires=arm3_fires,
        alpha=alpha,
        power=power,
        at_conservative_rate=detectable_difference(
            arm2_fires, arm3_fires, base_rate=CONSERVATIVE_BASE_RATE, alpha=alpha, power=power
        ),
        observed_rate=observed if informative else None,
        at_observed_rate=(
            detectable_difference(
                arm2_fires, arm3_fires, base_rate=observed, alpha=alpha, power=power
            )
            if informative and observed is not None
            else None
        ),
    )


def primary_report(
    arm2_outcomes: Sequence[PairOutcome],
    arm3_outcomes: Sequence[PairOutcome],
    *,
    baselines: Mapping[str, Sequence[PairOutcome]] | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
) -> PrimaryReport:
    """Assemble Figure 1 and its comparison for one regime.

    Both arms must have been run on the same pairs, so the outcome lists must be the same
    length and in one regime; every baseline likewise. `alpha` and `power` are item 3's
    defaults (ADR-0008 records them as defaults, not as a registered α).
    """
    if len(arm2_outcomes) != len(arm3_outcomes):
        raise ValueError(
            f"arm 2 has {len(arm2_outcomes)} outcomes and arm 3 has {len(arm3_outcomes)}; "
            f"the comparison is over one set of pairs"
        )
    if not arm3_outcomes:
        raise ValueError("no pairs to report on")
    informed = _regime([*arm2_outcomes, *arm3_outcomes])
    arm2 = _dispatcher("arm 2 (semantic)", arm2_outcomes)
    arm3 = operating_point(arm3_outcomes)
    fired_curve = [point for point in arm2.points if point.coverage.numerator > 0]
    matched = matched_comparison(fired_curve, arm3) if fired_curve else None

    extra: list[Dispatcher] = []
    for name, outcomes in (baselines or {}).items():
        if len(outcomes) != len(arm3_outcomes) or _regime(outcomes) != informed:
            raise ValueError(f"baseline {name!r} was not run on the same pairs and regime")
        extra.append(_dispatcher(name, outcomes))

    return PrimaryReport(
        informed=informed,
        pairs=len(arm3_outcomes),
        arm2=arm2,
        arm3=arm3,
        vacuous=vacuous_reason(arm3_outcomes),
        matched=matched,
        power=_power(matched, alpha=alpha, power=power) if matched is not None else None,
        baselines=extra,
    )


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}"


def summary(report: PrimaryReport) -> str:
    """The text a reader gets, with the vacuity guard ahead of any comparison."""
    regime = "informed" if report.informed else "uninformed"
    arm3 = report.arm3
    lines = [
        f"Primary metric, {regime} regime, {report.pairs} labelled pairs "
        "(spec §7 item 1, ADR-0008)",
        f"  arm 3 (pre-registered coverage point): coverage "
        f"{_rate(arm3.coverage.numerator, arm3.coverage.denominator)}, mismatch "
        f"{_rate(arm3.mismatch.numerator, arm3.mismatch.denominator)}",
        f"  arm 2 curve: {len(report.arm2.points)} operating point(s), each with a 95% "
        "Wilson interval in figure1.csv",
    ]
    if report.vacuous is not None:
        lines.append(f"  NO COMPARISON: {report.vacuous}")
    elif report.matched is None:
        lines.append("  NO COMPARISON: arm 2 fired on no pair at any threshold")
    else:
        matched = report.matched
        difference = (
            "undefined"
            if matched.mismatch_difference is None
            else f"{matched.mismatch_difference:+.4f}"
        )
        lines.append(
            f"  at matched coverage arm 2 (threshold {matched.arm2.threshold}) has mismatch "
            f"{_rate(matched.arm2.mismatch.numerator, matched.arm2.mismatch.denominator)}; "
            f"coverage gap {matched.coverage_gap:+.3f}; mismatch difference "
            f"(arm 2 - arm 3) {difference}"
        )
    if report.power is not None:
        stated = report.power
        conservative = (
            "undefined"
            if stated.at_conservative_rate is None
            else f"{stated.at_conservative_rate:.3f}"
        )
        lines.append(
            f"  power (item 3): with {stated.arm2_fires} and {stated.arm3_fires} fires, "
            f"alpha {stated.alpha} two-sided and power {stated.power}, the smallest "
            f"detectable mismatch difference is {conservative} at a "
            f"{CONSERVATIVE_BASE_RATE:.0%} base rate"
            + (
                f" and {stated.at_observed_rate:.3f} at the observed {stated.observed_rate:.3f}"
                if stated.at_observed_rate is not None and stated.observed_rate is not None
                else ""
            )
        )
    for baseline in report.baselines:
        lines.append(
            f"  baseline {baseline.name}: "
            + ("curve" if baseline.scored else "point")
            + f", {len(baseline.points)} operating point(s) -- context, not part of the claim"
        )
    return "\n".join(lines) + "\n"


_CSV_HEADER = [
    "dispatcher",
    "threshold",
    "fires",
    "pairs",
    "coverage",
    "wrong",
    "mismatch",
    "wilson_low",
    "wilson_high",
    "coverage_point",
]


def _csv_row(name: str, point: OperatingPoint, *, coverage_point: bool) -> list[object]:
    interval = point.mismatch_interval
    return [
        name,
        "" if point.threshold is None else point.threshold,
        point.coverage.numerator,
        point.coverage.denominator,
        "" if point.coverage.value is None else round(point.coverage.value, 6),
        point.mismatch.numerator,
        "" if point.mismatch.value is None else round(point.mismatch.value, 6),
        "" if interval is None else round(interval.low, 6),
        "" if interval is None else round(interval.high, 6),
        coverage_point,
    ]


def write_primary_report(report: PrimaryReport, dest: Path, *, plot: bool = True) -> Path:
    """Write `figure1.csv`, `primary.txt` and (with `plot`) `figure1.png` under `dest`.

    The CSV is the deliverable -- every operating point with its numerator, denominator
    and Wilson interval, and arm 3's row flagged as the coverage point -- and the PNG is
    a rendering of it. matplotlib is the `dev` extra, as for the episode report.
    """
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "figure1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_CSV_HEADER)
        for point in report.arm2.points:
            writer.writerow(_csv_row(report.arm2.name, point, coverage_point=False))
        writer.writerow(_csv_row("arm 3 (precondition)", report.arm3, coverage_point=True))
        for baseline in report.baselines:
            for point in baseline.points:
                writer.writerow(_csv_row(baseline.name, point, coverage_point=False))
    (dest / "primary.txt").write_text(summary(report), encoding="utf-8")
    if plot:
        _plot(report, dest / "figure1.png")
    return dest


def _errors(points: Sequence[OperatingPoint]) -> tuple[list[float], list[float], list[float]]:
    values = [point.mismatch.value or 0.0 for point in points]
    low = [
        value - (point.mismatch_interval.low if point.mismatch_interval else value)
        for value, point in zip(values, points, strict=True)
    ]
    high = [
        (point.mismatch_interval.high if point.mismatch_interval else value) - value
        for value, point in zip(values, points, strict=True)
    ]
    return values, low, high


def _plot(report: PrimaryReport, dest: Path) -> None:
    from .report import _pyplot

    plt = _pyplot()
    figure, axes = plt.subplots(figsize=(6.0, 4.5))
    dispatchers = [report.arm2, *report.baselines]
    for dispatcher in dispatchers:
        fired = [p for p in dispatcher.points if p.coverage.numerator > 0]
        if not fired:
            continue
        values, low, high = _errors(fired)
        axes.errorbar(
            [p.coverage.value or 0.0 for p in fired],
            values,
            yerr=[low, high],
            marker="o" if dispatcher.scored else "s",
            linestyle="-" if dispatcher.scored else "none",
            capsize=3,
            label=dispatcher.name,
        )
    if report.arm3.coverage.numerator > 0:
        values, low, high = _errors([report.arm3])
        axes.errorbar(
            [report.arm3.coverage.value or 0.0],
            values,
            yerr=[low, high],
            marker="*",
            markersize=12,
            linestyle="none",
            capsize=3,
            label="arm 3 (coverage point)",
        )
        axes.axvline(report.arm3.coverage.value or 0.0, linestyle=":", linewidth=1)
    axes.set_xlabel("coverage (fires / pairs)")
    axes.set_ylabel("mismatch (wrong fires / fires)")
    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.0)
    regime = "informed" if report.informed else "uninformed"
    title = f"Figure 1 -- mismatch vs coverage, {regime} regime"
    if report.vacuous is not None:
        title += "\n(vacuous: arm 3 is the labelling rule -- no comparison)"
    axes.set_title(title)
    axes.legend(loc="best", fontsize=8)
    figure.tight_layout()
    figure.savefig(dest, dpi=150)
    plt.close(figure)
