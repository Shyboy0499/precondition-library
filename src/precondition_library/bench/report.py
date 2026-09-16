"""Turn the ledger into the ablation table and the two demo figures.

What is primary, and what this module is not
--------------------------------------------
The pre-registered primary metric (spec §7, "Pre-registered analysis", revised
2026-09-13 before any data existed) is the **mismatch-versus-coverage curve at
matched coverage**, computed over labelled (repo-state, candidate-program)
dispatch pairs -- the seam in `bench.pairs` and the threshold sweep in issue #5.
This module does not compute it, and no number printed here is that measurement.

The episode loop `bench.run` writes is retained only as a demonstration and is
explicitly underpowered: 5 faults x 4 occurrences x 3 arms = 60 episodes, which
spec §7 excludes from the primary claim. So the two figures built here are:

* a **cost model** -- mean tokens and LLM calls per episode against
  `occurrence_index`, one series per arm. Secondary, and reported as a cost
  model rather than as a result; the token curve is not the finding.
* an **episode-level arm 2 vs arm 3 mismatch comparison at matched N** -- the
  demo's comparative number, reported with a Wilson interval, not the
  pre-registered claim. Its note says so in the output.

Every rate carries its numerator and its denominator, and every mean carries the
number of episodes it averaged. A rate over a handful of episodes is noise, so
it travels with a Wilson interval and, below a small-N guard, a sentence saying
so. `invalid` episodes -- the ones that could not run -- are excluded from every
metric denominator and reported as their own rate, never dropped: an invalid
rate above 10% makes the run suspect (spec §7, item 9).

Figures need a plotting library. `matplotlib` is already declared in the `dev`
extra in `pyproject.toml` (alongside `pandas`), so this module uses it and adds
no dependency. The PNGs are renderings of numbers that are also written as CSV;
the CSV is the deliverable, the picture is a convenience.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..program import EpisodeOutcome
from .ledger import Arm, EpisodeRecord, read

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


class AblationRow(BaseModel):
    """One (arm, fault, occurrence) cell, with every denominator attached.

    `episodes` counts every row in the cell, `invalid` included, because that is
    the denominator of the invalid rate. `graded_episodes` is the cell minus its
    invalid rows, and it is the denominator of `success`, `mismatch` and every
    mean: an episode that never ran cannot be right or wrong, and averaging its
    (absent) cost into the means would be the spec's "hidden invalid" defect.
    """

    arm: Arm
    fault_type: str
    occurrence_index: int
    episodes: int
    graded_episodes: int
    invalid: Rate
    success: Rate
    mismatch: Rate
    mean_tokens: Mean
    mean_cached_tokens_in: Mean
    mean_llm_calls: Mean
    mean_wall_clock_s: Mean


class CostPoint(BaseModel):
    """One point of the secondary cost model, for one arm at one occurrence."""

    arm: Arm
    occurrence_index: int
    episodes: int
    mean_tokens: Mean
    mean_cached_tokens_in: Mean
    mean_llm_calls: Mean


class ArmMismatch(BaseModel):
    """One arm's side of the matched comparison."""

    arm: Arm
    available: int
    """Graded episodes this arm has in the ledger, before matching."""
    matched_n: int
    """Graded episodes used; equal across the two arms by construction."""
    mismatch: Rate
    interval: Interval | None


class MismatchComparison(BaseModel):
    """Arm 2 vs arm 3 mismatch at matched N -- the demo's number, not the claim."""

    matched_n: int
    semantic: ArmMismatch
    precondition: ArmMismatch
    note: str


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
    return Interval(low=max(0.0, centre - margin), high=min(1.0, centre + margin))


def _graded(records: Iterable[EpisodeRecord]) -> list[EpisodeRecord]:
    """Every episode that actually ran. Invalid rows are accounted for elsewhere."""
    return [record for record in records if record.outcome is not EpisodeOutcome.INVALID]


def _mean(values: Iterable[int | float]) -> Mean:
    """The mean, carrying the count it was taken over; None for an empty group."""
    materialised = [float(value) for value in values]
    if not materialised:
        return Mean(n=0, value=None)
    return Mean(n=len(materialised), value=sum(materialised) / len(materialised))


def _rows(
    group: list[EpisodeRecord],
) -> tuple[list[EpisodeRecord], int, Rate, Rate, Rate, Mean, Mean, Mean, Mean]:
    """The shared arithmetic for one cell: graded rows, counts, rates and means."""
    graded = _graded(group)
    return (
        graded,
        len(group),
        Rate(numerator=len(group) - len(graded), denominator=len(group)),
        Rate(numerator=sum(1 for r in graded if r.succeeded), denominator=len(graded)),
        Rate(numerator=sum(1 for r in graded if r.misfired), denominator=len(graded)),
        _mean(r.tokens_in + r.tokens_out for r in graded),
        _mean(r.cached_tokens_in for r in graded),
        _mean(r.llm_calls for r in graded),
        _mean(r.wall_clock_s for r in graded),
    )


def ablation_table(ledger: Path) -> list[AblationRow]:
    """Wide table: one row per (arm, fault_type, occurrence_index).

    Columns include episodes, success rate, mismatch rate, mean tokens,
    mean LLM calls, and mean wall clock -- each with its denominator. There is
    deliberately no total row: summing cells of different sizes would bury a
    small denominator inside a large one.
    """
    groups: dict[tuple[Arm, str, int], list[EpisodeRecord]] = {}
    for record in read(ledger):
        key = (record.arm, record.fault_type, record.occurrence_index)
        groups.setdefault(key, []).append(record)

    rows: list[AblationRow] = []
    for key in sorted(groups, key=lambda k: (k[0].value, k[1], k[2])):
        arm, fault_type, occurrence = key
        group = groups[key]
        graded, episodes, invalid, success, mismatch, tokens, cached, calls, wall = _rows(group)
        rows.append(
            AblationRow(
                arm=arm,
                fault_type=fault_type,
                occurrence_index=occurrence,
                episodes=episodes,
                graded_episodes=len(graded),
                invalid=invalid,
                success=success,
                mismatch=mismatch,
                mean_tokens=tokens,
                mean_cached_tokens_in=cached,
                mean_llm_calls=calls,
                mean_wall_clock_s=wall,
            )
        )
    return rows


def cost_curve(ledger: Path) -> list[CostPoint]:
    """Figure 1. Mean tokens per episode against occurrence_index, per arm.

    A secondary cost model, not a result. Grouping is by (arm, occurrence_index)
    and never merges arms: the comparison of the slopes is the only thing the
    curve is for, and pooling two arms would erase it. Invalid episodes are
    excluded; they spent no tokens.
    """
    groups: dict[tuple[Arm, int], list[EpisodeRecord]] = {}
    for record in _graded(read(ledger)):
        key = (record.arm, record.occurrence_index)
        groups.setdefault(key, []).append(record)

    points: list[CostPoint] = []
    for key in sorted(groups, key=lambda k: (k[0].value, k[1])):
        arm, occurrence = key
        group = groups[key]
        points.append(
            CostPoint(
                arm=arm,
                occurrence_index=occurrence,
                episodes=len(group),
                mean_tokens=_mean(r.tokens_in + r.tokens_out for r in group),
                mean_cached_tokens_in=_mean(r.cached_tokens_in for r in group),
                mean_llm_calls=_mean(r.llm_calls for r in group),
            )
        )
    return points


def _by_seed(records: list[EpisodeRecord]) -> list[EpisodeRecord]:
    """A deterministic order for choosing which episodes survive matching."""
    return sorted(records, key=lambda r: (r.seed, r.task_id))


def _match_strata(
    left: list[EpisodeRecord], right: list[EpisodeRecord]
) -> tuple[list[EpisodeRecord], list[EpisodeRecord]]:
    """The two arms restricted to common (fault, occurrence) strata, matched on N.

    Matching on the stratum rather than truncating a tail keeps every fault and
    occurrence weighted the same in both arms; dropping a tail would quietly
    turn the comparison into "the first k episodes", which is a different
    experiment. Within a stratum, episodes are chosen in seed order. Episodes in
    no common stratum stay out of the matched rate and are reported in
    `available`, so nothing is dropped silently.
    """
    left_groups: dict[tuple[str, int], list[EpisodeRecord]] = {}
    right_groups: dict[tuple[str, int], list[EpisodeRecord]] = {}
    for record in left:
        left_groups.setdefault((record.fault_type, record.occurrence_index), []).append(record)
    for record in right:
        right_groups.setdefault((record.fault_type, record.occurrence_index), []).append(record)

    matched_left: list[EpisodeRecord] = []
    matched_right: list[EpisodeRecord] = []
    for stratum in sorted(set(left_groups) & set(right_groups)):
        shared = min(len(left_groups[stratum]), len(right_groups[stratum]))
        matched_left.extend(_by_seed(left_groups[stratum])[:shared])
        matched_right.extend(_by_seed(right_groups[stratum])[:shared])
    return matched_left, matched_right


def _arm_mismatch(
    arm: Arm, available: list[EpisodeRecord], matched: list[EpisodeRecord]
) -> ArmMismatch:
    rate = Rate(
        numerator=sum(1 for record in matched if record.misfired),
        denominator=len(matched),
    )
    return ArmMismatch(
        arm=arm,
        available=len(available),
        matched_n=len(matched),
        mismatch=rate,
        interval=rate.interval,
    )


def _comparison_note(matched_n: int, semantic_available: int, precondition_available: int) -> str:
    parts = [
        "Episode-level demo, not the pre-registered analysis: the primary metric is "
        "mismatch vs coverage at matched coverage over labelled dispatch pairs (spec "
        "§7), the episode loop is underpowered, and it is excluded from that claim.",
        f"Matched N={matched_n} (arm 2 has {semantic_available} graded episode(s), arm 3 "
        f"{precondition_available}); any episode outside a common stratum is reported in "
        "`available`, not dropped silently.",
    ]
    if matched_n == 0:
        parts.append("No graded episode is common to both arms, so no rate is reported.")
    elif matched_n < SMALL_SAMPLE_N:
        parts.append(
            f"N={matched_n} is below the small-sample guard of {SMALL_SAMPLE_N}: the "
            "intervals are wide and these rates should be read as noise, not as a finding."
        )
    return " ".join(parts)


def mismatch_comparison(ledger: Path) -> MismatchComparison:
    """Figure 2. Arm 2 vs arm 3 mismatch rate, with intervals, matched on N.

    `misfired` is the ledger's derived property -- a fired variant that was not
    the ground-truth one -- not a stored outcome, so this counts the quadrant the
    metric exists for: a wrong fire in an episode that still succeeded. Invalid
    episodes are excluded from the rates and their absence is reported in
    `available`.
    """
    records = _graded(read(ledger))
    semantic = [record for record in records if record.arm is Arm.SEMANTIC]
    precondition = [record for record in records if record.arm is Arm.PRECONDITION]
    matched_semantic, matched_precondition = _match_strata(semantic, precondition)
    matched_n = len(matched_semantic)
    return MismatchComparison(
        matched_n=matched_n,
        semantic=_arm_mismatch(Arm.SEMANTIC, semantic, matched_semantic),
        precondition=_arm_mismatch(Arm.PRECONDITION, precondition, matched_precondition),
        note=_comparison_note(matched_n, len(semantic), len(precondition)),
    )


def _overall_invalid(rows: list[AblationRow]) -> Rate:
    return Rate(
        numerator=sum(row.invalid.numerator for row in rows),
        denominator=sum(row.episodes for row in rows),
    )


def _cell(value: object) -> str:
    """One CSV cell; None becomes empty rather than a misleading zero."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows([[_cell(value) for value in row] for row in rows])


def _write_ablation_csv(path: Path, rows: list[AblationRow]) -> None:
    header = [
        "arm",
        "fault_type",
        "occurrence_index",
        "episodes",
        "graded_episodes",
        "invalid_numerator",
        "invalid_denominator",
        "invalid_rate",
        "success_numerator",
        "success_denominator",
        "success_rate",
        "mismatch_numerator",
        "mismatch_denominator",
        "mismatch_rate",
        "mean_tokens",
        "mean_tokens_n",
        "mean_cached_tokens_in",
        "mean_cached_tokens_in_n",
        "mean_llm_calls",
        "mean_llm_calls_n",
        "mean_wall_clock_s",
        "mean_wall_clock_s_n",
    ]
    _write_csv(
        path,
        header,
        [
            [
                row.arm.value,
                row.fault_type,
                row.occurrence_index,
                row.episodes,
                row.graded_episodes,
                row.invalid.numerator,
                row.invalid.denominator,
                row.invalid.value,
                row.success.numerator,
                row.success.denominator,
                row.success.value,
                row.mismatch.numerator,
                row.mismatch.denominator,
                row.mismatch.value,
                row.mean_tokens.value,
                row.mean_tokens.n,
                row.mean_cached_tokens_in.value,
                row.mean_cached_tokens_in.n,
                row.mean_llm_calls.value,
                row.mean_llm_calls.n,
                row.mean_wall_clock_s.value,
                row.mean_wall_clock_s.n,
            ]
            for row in rows
        ],
    )


def _write_cost_csv(path: Path, points: list[CostPoint]) -> None:
    header = [
        "arm",
        "occurrence_index",
        "episodes",
        "mean_tokens",
        "mean_tokens_n",
        "mean_cached_tokens_in",
        "mean_cached_tokens_in_n",
        "mean_llm_calls",
        "mean_llm_calls_n",
    ]
    _write_csv(
        path,
        header,
        [
            [
                point.arm.value,
                point.occurrence_index,
                point.episodes,
                point.mean_tokens.value,
                point.mean_tokens.n,
                point.mean_cached_tokens_in.value,
                point.mean_cached_tokens_in.n,
                point.mean_llm_calls.value,
                point.mean_llm_calls.n,
            ]
            for point in points
        ],
    )


def _write_mismatch_csv(path: Path, comparison: MismatchComparison) -> None:
    header = [
        "arm",
        "available_graded_episodes",
        "matched_n",
        "mismatch_numerator",
        "mismatch_denominator",
        "mismatch_rate",
        "interval_low",
        "interval_high",
    ]
    rows: list[list[object]] = []
    for side in (comparison.semantic, comparison.precondition):
        interval = side.interval
        rows.append(
            [
                side.arm.value,
                side.available,
                side.matched_n,
                side.mismatch.numerator,
                side.mismatch.denominator,
                side.mismatch.value,
                interval.low if interval is not None else None,
                interval.high if interval is not None else None,
            ]
        )
    _write_csv(path, header, rows)


def _pyplot() -> Any:
    """matplotlib's pyplot on the headless backend, imported only when plotting."""
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    return plt


def _plot_cost_curve(points: list[CostPoint], dest: Path) -> None:
    plt = _pyplot()
    figure, axes = plt.subplots(figsize=(7.0, 4.0))
    for arm in sorted({point.arm for point in points}, key=lambda candidate: candidate.value):
        series = [point for point in points if point.arm is arm]
        axes.plot(
            [point.occurrence_index for point in series],
            [point.mean_tokens.value for point in series],
            marker="o",
            label=arm.value,
        )
    axes.set_xlabel("occurrence index")
    axes.set_ylabel("mean tokens per episode")
    axes.set_title("Cost vs repeat -- secondary, underpowered episode demo")
    axes.legend(title="arm")
    figure.savefig(dest, dpi=150)
    plt.close(figure)


def _plot_mismatch_comparison(comparison: MismatchComparison, dest: Path) -> None:
    plt = _pyplot()
    sides = (comparison.semantic, comparison.precondition)
    values = [side.mismatch.value if side.mismatch.value is not None else 0.0 for side in sides]
    lower = [
        value - (side.interval.low if side.interval is not None else value)
        for value, side in zip(values, sides)
    ]
    upper = [
        (side.interval.high if side.interval is not None else value) - value
        for value, side in zip(values, sides)
    ]
    figure, axes = plt.subplots(figsize=(5.5, 4.0))
    axes.bar(
        [side.arm.value for side in sides],
        values,
        yerr=[lower, upper],
        capsize=6,
    )
    axes.set_ylabel("mismatch rate")
    axes.set_ylim(0.0, 1.0)
    axes.set_title(f"Mismatch at matched N={comparison.matched_n} -- underpowered demo")
    figure.savefig(dest, dpi=150)
    plt.close(figure)


def _format_rate(rate: Rate) -> str:
    rendered = "undefined" if rate.value is None else f"{rate.value:.3f}"
    return f"{rate.numerator}/{rate.denominator} ({rendered})"


def _format_mean(mean: Mean, label: str) -> str:
    rendered = "undefined" if mean.value is None else f"{mean.value:.4g}"
    return f"{label}={rendered} (n={mean.n})"


def _summary(
    rows: list[AblationRow], points: list[CostPoint], comparison: MismatchComparison
) -> str:
    invalid = _overall_invalid(rows)
    lines = [
        "Precondition-library ablation report",
        "====================================",
        "",
        "This report is NOT the pre-registered primary analysis. The primary metric is",
        "mismatch vs coverage at matched coverage over labelled dispatch pairs (spec §7).",
        "The episode loop behind these numbers is the underpowered demo, excluded from",
        "that claim; the figures below are a secondary cost model and a demo comparison.",
        "",
        f"Invalid episodes (excluded from every metric denominator): {_format_rate(invalid)}.",
    ]
    if invalid.value is not None and invalid.value > INVALID_RATE_ALARM:
        lines.append(
            f"  ABOVE {INVALID_RATE_ALARM:.0%}: the run is suspect and should be re-run, "
            "not analysed (spec §7, item 9)."
        )
    lines += ["", "Ablation table (one row per arm, fault, occurrence):"]
    if not rows:
        lines.append("  (the ledger is empty; no cell has a denominator to report)")
    for row in rows:
        lines.append(
            f"  {row.arm.value} {row.fault_type} occ={row.occurrence_index}"
            f" episodes={row.episodes} graded={row.graded_episodes}"
            f" invalid={_format_rate(row.invalid)}"
            f" success={_format_rate(row.success)}"
            f" mismatch={_format_rate(row.mismatch)}"
            f" {_format_mean(row.mean_tokens, 'tokens')}"
            f" {_format_mean(row.mean_llm_calls, 'llm_calls')}"
            f" {_format_mean(row.mean_wall_clock_s, 'wall_s')}"
        )
    lines += ["", "Cost curve (secondary; a cost model, not a result):"]
    if not points:
        lines.append("  (no graded episode, so no curve)")
    for point in points:
        lines.append(
            f"  {point.arm.value} occ={point.occurrence_index} episodes={point.episodes}"
            f" {_format_mean(point.mean_tokens, 'tokens')}"
            f" {_format_mean(point.mean_llm_calls, 'llm_calls')}"
        )
    lines += ["", f"Mismatch comparison (arm 2 vs arm 3, matched N={comparison.matched_n}):"]
    for side in (comparison.semantic, comparison.precondition):
        interval = side.interval
        rendered = (
            "undefined"
            if interval is None
            else f"95% Wilson [{interval.low:.3f}, {interval.high:.3f}]"
        )
        lines.append(
            f"  {side.arm.value} available={side.available} matched_n={side.matched_n}"
            f" mismatch={_format_rate(side.mismatch)} {rendered}"
        )
    lines += [
        f"  note: {comparison.note}",
        "",
        "Figures: cost_curve.png and mismatch_comparison.png. matplotlib is declared in",
        "pyproject.toml's `dev` extra, so no dependency was added; the CSVs beside them",
        "carry the same numbers and are the deliverable.",
        "",
    ]
    return "\n".join(lines)


def write_report(ledger: Path, dest: Path) -> Path:
    """Emit the tables and figures into `dest` for the README to embed.

    Writes `ablation_table.csv`, `cost_curve.csv` and `mismatch_comparison.csv`
    (the numbers, each rate beside its denominator), `cost_curve.png` and
    `mismatch_comparison.png` (renderings of those numbers) and `report.txt`
    (the caveats, the invalid rate, and the plain statement that the primary
    pre-registered analysis is not here). Returns `dest`.
    """
    rows = ablation_table(ledger)
    points = cost_curve(ledger)
    comparison = mismatch_comparison(ledger)

    dest.mkdir(parents=True, exist_ok=True)
    _write_ablation_csv(dest / "ablation_table.csv", rows)
    _write_cost_csv(dest / "cost_curve.csv", points)
    _write_mismatch_csv(dest / "mismatch_comparison.csv", comparison)
    _plot_cost_curve(points, dest / "cost_curve.png")
    _plot_mismatch_comparison(comparison, dest / "mismatch_comparison.png")
    (dest / "report.txt").write_text(_summary(rows, points, comparison), encoding="utf-8")
    return dest
