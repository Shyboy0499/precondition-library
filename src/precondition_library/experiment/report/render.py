"""The report written out: CSVs, figures and the summary text."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from precondition_library.experiment.ledger import Arm, OccurrenceRole
from precondition_library.experiment.report.stats import (
    EQUIVALENCE_MARGIN,
    INVALID_RATE_ALARM,
    TOST_ALPHA,
    Mean,
    Rate,
    success_rate_wording,
)
from precondition_library.experiment.report.tables import (
    AblationRow,
    AchievedInstance,
    ArmTriple,
    CostPoint,
    FaultSurface,
    MismatchComparison,
    ParetoFrontier,
    _overall_invalid,
    _overall_spec_gaming,
    ablation_table,
    achieved_instances,
    arm_triples,
    break_even,
    change_surfaces,
    cost_curve,
    mismatch_comparison,
    occurrence_counts,
    pareto_frontier,
    prompt_prefix_lengths,
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


def _write_triple_csv(path: Path, triples: list[ArmTriple], pareto: ParetoFrontier) -> None:
    on_frontier = set(pareto.frontier)
    by_arm: dict[Arm, list[str]] = {}
    for item in pareto.dominated:
        by_arm[item.arm] = [dominator.value for dominator in item.dominated_by]
    header = [
        "arm",
        "graded_episodes",
        "success_numerator",
        "success_denominator",
        "success_rate",
        "tokens_per_episode",
        "tokens_per_episode_n",
        "tokens_per_success",
        "tokens_per_success_n",
        "on_frontier",
        "dominated_by",
    ]
    _write_csv(
        path,
        header,
        [
            [
                triple.arm.value,
                triple.graded_episodes,
                triple.success.numerator,
                triple.success.denominator,
                triple.success.value,
                triple.tokens_per_episode.value,
                triple.tokens_per_episode.n,
                triple.tokens_per_success.value,
                triple.tokens_per_success.n,
                triple.arm in on_frontier,
                " ".join(by_arm.get(triple.arm, [])),
            ]
            for triple in triples
        ],
    )


def _plot_pareto(triples: list[ArmTriple], pareto: ParetoFrontier, dest: Path) -> None:
    """Two of the three axes are drawn, and the third is annotated on each point.

    A three-metric frontier cannot be drawn faithfully on a plane: any projection
    hides dominance that the third axis would have shown. So the plot does not claim
    to be the frontier. It draws tokens per episode against success rate with the
    frontier marked, and prints each arm's tokens per success beside its point; the
    frontier itself is computed on all three and stated in the report text and the CSV.
    """
    plt = _pyplot()
    figure, axes = plt.subplots(figsize=(7.0, 4.5))
    for label, group, marker in (
        ("on the frontier", [t for t in triples if t.arm in set(pareto.frontier)], "o"),
        ("dominated", [t for t in triples if t.arm not in set(pareto.frontier)], "x"),
    ):
        if not group:
            continue
        axes.scatter(
            [t.tokens_per_episode.value for t in group],
            [t.success.value for t in group],
            marker=marker,
            s=60,
            label=label,
        )
    for triple in triples:
        per_success = triple.tokens_per_success.value
        annotation = (
            f"{triple.arm.value}\n{per_success:,.0f} tok/success"
            if per_success is not None
            else f"{triple.arm.value}\nno success"
        )
        axes.annotate(
            annotation,
            (triple.tokens_per_episode.value, triple.success.value),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=8,
        )
    axes.set_xlabel("tokens per episode (lower is better)")
    axes.set_ylabel("success rate (higher is better)")
    axes.set_title("The triple: cost per episode vs success, cost per success annotated")
    if triples:
        axes.legend(title="Pareto")
    figure.savefig(dest, dpi=150)
    plt.close(figure)


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
        "spec_gaming_numerator",
        "spec_gaming_denominator",
        "spec_gaming_rate",
        "mean_tokens",
        "mean_tokens_n",
        "mean_embedding_tokens",
        "mean_embedding_tokens_n",
        "mean_embedding_calls",
        "mean_embedding_calls_n",
        "mean_uncached_tokens_in",
        "mean_uncached_tokens_in_n",
        "mean_cached_tokens_in",
        "mean_cached_tokens_in_n",
        "mean_cache_write_tokens_in",
        "mean_cache_write_tokens_in_n",
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
                row.spec_gaming.numerator,
                row.spec_gaming.denominator,
                row.spec_gaming.value,
                row.mean_tokens.value,
                row.mean_tokens.n,
                row.mean_embedding_tokens.value,
                row.mean_embedding_tokens.n,
                row.mean_embedding_calls.value,
                row.mean_embedding_calls.n,
                row.mean_uncached_tokens_in.value,
                row.mean_uncached_tokens_in.n,
                row.mean_cached_tokens_in.value,
                row.mean_cached_tokens_in.n,
                row.mean_cache_write_tokens_in.value,
                row.mean_cache_write_tokens_in.n,
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
        "occurrence_role",
        "occurrence_index",
        "episodes",
        "mean_tokens",
        "mean_tokens_n",
        "mean_cached_tokens_in",
        "mean_cached_tokens_in_n",
        "mean_llm_calls",
        "mean_llm_calls_n",
        "cumulative_tokens",
        "cumulative_tokens_n",
        "cumulative_llm_calls",
        "cumulative_llm_calls_n",
    ]
    _write_csv(
        path,
        header,
        [
            [
                point.arm.value,
                point.occurrence_role.value,
                point.occurrence_index,
                point.episodes,
                point.mean_tokens.value,
                point.mean_tokens.n,
                point.mean_cached_tokens_in.value,
                point.mean_cached_tokens_in.n,
                point.mean_llm_calls.value,
                point.mean_llm_calls.n,
                point.cumulative_tokens.value,
                point.cumulative_tokens.n,
                point.cumulative_llm_calls.value,
                point.cumulative_llm_calls.n,
            ]
            for point in points
        ],
    )


def _write_mismatch_csv(path: Path, comparison: MismatchComparison) -> None:
    header = [
        "arm",
        "occurrence_role",
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
                comparison.occurrence_role.value,
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
    arms = sorted({point.arm for point in points}, key=lambda candidate: candidate.value)
    for arm in arms:
        series = [point for point in points if point.arm is arm]
        axes.plot(
            [point.occurrence_index for point in series],
            [point.cumulative_tokens.value for point in series],
            marker="o",
            label=arm.value,
        )
    for finding in break_even(points):
        if finding.occurrence_index is None:
            continue
        # Marked rather than left to the reader: the crossing is the finding, and a
        # figure where it has to be eyeballed is one a reader can misread.
        axes.axvline(
            finding.occurrence_index,
            linestyle="--",
            linewidth=1.0,
            label=f"{finding.arm.value} break-even",
        )
    axes.set_xlabel("occurrence index (replay occurrences only)")
    axes.set_ylabel("cumulative amortized tokens per episode")
    axes.set_title("Cumulative amortized cost vs repeat -- secondary, underpowered demo")
    if arms:
        # No labeled artist means no legend to draw; the report text carries the
        # explanation of the empty curve, and an empty figure is the honest
        # picture of a run that never revisited a state.
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
    axes.set_title(
        f"Mismatch at matched N={comparison.matched_n}, variant occurrences -- underpowered demo"
    )
    figure.savefig(dest, dpi=150)
    plt.close(figure)


def _format_rate(rate: Rate) -> str:
    rendered = "undefined" if rate.value is None else f"{rate.value:.3f}"
    return f"{rate.numerator}/{rate.denominator} ({rendered})"


def _format_mean(mean: Mean, label: str) -> str:
    rendered = "undefined" if mean.value is None else f"{mean.value:.4g}"
    return f"{label}={rendered} (n={mean.n})"


def _format_surface(surface: tuple[str, ...]) -> str:
    """One change surface for the report; the empty declaration is said in words.

    An empty surface prints as a phrase rather than as a blank, because a blank would read
    as missing data when an applied empty surface is the strictest declaration a fault can
    make (#96).
    """
    if not surface:
        return "(empty surface: committed content must not change)"
    return ", ".join(surface)


def _summary(
    rows: list[AblationRow],
    points: list[CostPoint],
    comparison: MismatchComparison,
    counts: dict[OccurrenceRole, int],
    triples: list[ArmTriple],
    pareto: ParetoFrontier,
    surfaces: list[FaultSurface],
    instances: list[AchievedInstance],
) -> str:
    sections = [
        _header_lines(rows, counts),
        _surface_lines(surfaces),
        _instance_lines(instances),
        _ablation_lines(rows),
        _cost_curve_lines(points),
        _triple_lines(triples),
        _pareto_lines(pareto),
        _seam_lines(rows),
        _prefix_lines(),
        _equivalence_lines(triples),
        _mismatch_lines(comparison),
    ]
    return "\n".join(line for section in sections for line in section)


def _header_lines(rows: list[AblationRow], counts: dict[OccurrenceRole, int]) -> list[str]:
    """The title, the warning that this is not the primary analysis, and the run's health:
    invalid and spec-gaming rates and the occurrence roles."""
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
        "Occurrences by role (graded rows): "
        f"{OccurrenceRole.VARIANT.value}={counts[OccurrenceRole.VARIANT]} "
        f"{OccurrenceRole.REPLAY.value}={counts[OccurrenceRole.REPLAY]}. A variant is the "
        "first sight of",
        "an instance (a resolution plus its drawn axis values) and is the only kind of "
        "independent observation; a replay is a genuine repeat of one. The cost curve uses "
        "the replays, the mismatch comparison",
        "the variants, and each figure says so below. `bench.splits` declares the roles.",
    ]
    if invalid.value is not None and invalid.value > INVALID_RATE_ALARM:
        lines.append(
            f"  ABOVE {INVALID_RATE_ALARM:.0%}: the run is suspect and should be re-run, "
            "not analysed (spec §7, item 9)."
        )
    gaming = _overall_spec_gaming(rows)
    lines.append(
        f"Spec-gaming (graded episodes that reached the expected state by "
        f"destroying recorded state): {_format_rate(gaming)}."
    )
    if gaming.numerator:
        lines.append(
            "  These rows carry `ground_truth_ok=False` and would otherwise read as "
            "resolutions that simply failed to repair the fault; `tasks/invariants.py` "
            "names which recorded ref was lost or rewritten (issue #9)."
        )
    return lines


def _surface_lines(surfaces: list[FaultSurface]) -> list[str]:
    """Each fault's change surface as its rows applied it (#96)."""
    lines: list[str] = []
    lines.append(
        "Change surface per fault (#96): the paths each fault's resolution was allowed to "
        "touch, as applied. Read from the ledger's `change_surface`, not from the fault "
        "registry, because spec-gaming is derived from the surface a row was actually "
        "graded against. `None` on a row means the check did not run (an invalid episode, a "
        "fault-level failure before the surface was applied, or a row predating the field); "
        "an empty surface is a declaration that committed content must not change:"
    )
    if not surfaces:
        lines.append("  no rows in this ledger, so no fault has a surface to report")
    for fault_surface in surfaces:
        lines.append(
            f"  {fault_surface.fault_type}:"
            f" applied={fault_surface.applied}/{fault_surface.episodes}"
        )
        if not fault_surface.surfaces:
            lines.append("    no row applied a surface (the check did not run on any of them)")
        elif fault_surface.disagreement:
            lines.append(
                f"    INCONSISTENT: {len(fault_surface.surfaces)} different surfaces were applied "
                "by this fault's rows, so the run does not agree with itself:"
            )
            for applied in fault_surface.surfaces:
                lines.append(
                    f"      {_format_surface(applied.surface)} ({applied.episodes} row(s))"
                )
        else:
            (only,) = fault_surface.surfaces
            lines.append(f"    {_format_surface(only.surface)} ({only.episodes} row(s))")
    return lines


def _instance_lines(instances: list[AchievedInstance]) -> list[str]:
    """The independent instances each resolution's seeds built (ADR-0005 decision 8)."""
    lines: list[str] = []
    lines.append(
        "Achieved instance count per resolution (ADR-0005 decision 8): the independent "
        "environments the run's seeds actually build, read from `instance_for_seed`. "
        "This is the number the comparison's power depends on, and it is not the seed "
        "count -- more seeds that draw one instance buy replays, not independence:"
    )
    if not instances:
        lines.append("  no measurable row in this ledger, so no resolution has an instance count")
    for achieved in instances:
        lines.append(
            f"  {achieved.fault_type}/{achieved.resolution}:"
            f" {achieved.instances} instance(s) over {achieved.seeds} seed(s)"
        )
    return lines


def _ablation_lines(rows: list[AblationRow]) -> list[str]:
    """One line per ablation cell."""
    lines: list[str] = []
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
    return lines


def _cost_curve_lines(points: list[CostPoint]) -> list[str]:
    """The secondary cost curve over replay occurrences, and its break-even in words."""
    lines: list[str] = []
    lines += [
        "",
        "Cost curve (secondary; replay occurrences only -- the ones a library could "
        "answer; a cost model, not a result). `tokens` is the provider's reported total "
        "and is NOT a billing basis: input is metered as uncached + cache-read + "
        "cache-write in `ablation_table.csv`, and a cache hit is billed at a fraction of "
        "a miss, so pricing this total at one rate overstates any arm that caches:",
    ]
    if not points:
        lines.append(
            "  (no graded replay occurrence in this ledger, so no curve: with no state "
            "revisited, nothing about amortization can be read off the run)"
        )
    for point in points:
        lines.append(
            f"  {point.arm.value} occ={point.occurrence_index} episodes={point.episodes}"
            f" {_format_mean(point.mean_tokens, 'tokens')}"
            f" {_format_mean(point.mean_llm_calls, 'llm_calls')}"
            f" | {_format_mean(point.cumulative_tokens, 'cumulative tokens/episode')}"
        )
    # The crossing is what the figure is read for, so it is stated in words as well
    # as drawn: a reader of report.txt alone must not have to eyeball a plot, and a
    # run that cannot show a crossover has to say so rather than leave a blank.
    findings = break_even(points)
    if not points:
        lines.append("  break-even: not computable -- there is no curve to cross")
    elif not findings:
        lines.append(
            "  break-even: not computable -- only one arm has replay occurrences, so "
            "there is nothing to compare against"
        )
    for finding in findings:
        lines.append(f"  break-even: {finding.detail}")
    return lines


def _triple_lines(triples: list[ArmTriple]) -> list[str]:
    """Each arm's pooled success and cost, and what the gold oracle floor means."""
    lines: list[str] = []
    lines += [
        "",
        "Arm triples (secondary; pooled over every graded episode of the arm, failed ones "
        "included -- the cell table is the detail):",
    ]
    for triple in triples:
        per_success = triple.tokens_per_success
        rendered_success = (
            "undefined (no episode reached the expected state)"
            if per_success.value is None
            else _format_mean(per_success, "tokens/success")
        )
        lines.append(
            f"  {triple.arm.value} graded={triple.graded_episodes}"
            f" success={_format_rate(triple.success)}"
            f" {_format_mean(triple.tokens_per_episode, 'tokens/episode')}"
            f" {rendered_success}"
        )
    gold = next((triple for triple in triples if triple.arm is Arm.GOLD), None)
    if gold is not None:
        lines.append(
            "  gold is the oracle floor (issue #7): it replays the ground-truth variant's "
            "hand-written resolution at zero LLM tokens, so its success bounds what any arm "
            "could reach here and its cost bounds the cheapest an arm could be. It is an "
            "oracle, not a dispatcher, so it is absent from the matched-coverage comparison."
        )
    return lines


def _pareto_lines(pareto: ParetoFrontier) -> list[str]:
    """Which arms are on the cost-success frontier and which are dominated."""
    lines: list[str] = []
    lines.append(
        "Pareto over the arms (an arm is only dominated if it is no better on success "
        "and no cheaper on both costs):"
    )
    if pareto.frontier:
        lines.append(f"  on the frontier: {', '.join(a.value for a in pareto.frontier)}")
    else:
        lines.append("  on the frontier: none -- no arm has a cost per success to rank")
    for item in pareto.dominated:
        lines.append(
            f"  dominated: {item.arm.value} by {', '.join(a.value for a in item.dominated_by)}"
        )
    if pareto.unranked:
        lines.append(
            "  unranked (no success to divide by, so not compared): "
            f"{', '.join(a.value for a in pareto.unranked)}"
        )
    return lines


def _seam_lines(rows: list[AblationRow]) -> list[str]:
    """Arm 2's similarity-seam spend, kept apart from the LLM's tokens."""
    lines: list[str] = []
    lines.append(
        "Similarity-seam currency (arm 2 only; never added to the LLM token counts, "
        "because one arm pays it and the others do not):"
    )
    if not rows:
        lines.append("  no cells in this ledger")
    for row in rows:
        if row.mean_embedding_tokens.value:
            lines.append(
                f"  {row.arm.value} {row.fault_type} occ={row.occurrence_index}:"
                f" {_format_mean(row.mean_embedding_tokens, 'embedding tokens')}"
                f" {_format_mean(row.mean_embedding_calls, 'embedding calls')}"
            )
    if not any(row.mean_embedding_tokens.value for row in rows):
        lines.append("  0: the seam is lexical and spends nothing, so no arm pays a second bill")
    return lines


def _prefix_lines() -> list[str]:
    """The prompt prefixes every arm sends."""
    lines: list[str] = []
    lines.append(
        "Prompt prefixes the run sends (raw characters, shared by every arm -- the "
        "per-arm difference is transcript growth around the prefix, not the prefix):"
    )
    for prefix in prompt_prefix_lengths():
        lines.append(f"  {prefix.phase}: {prefix.chars:,} chars -- {prefix.source}")
    return lines


def _equivalence_lines(triples: list[ArmTriple]) -> list[str]:
    """The pre-registered success-rate equivalence test between the dispatch arms."""
    lines: list[str] = []
    lines.append(
        f"Success-rate equivalence (pre-registered TOST, margin +/-{EQUIVALENCE_MARGIN:.0%}, "
        f"alpha {TOST_ALPHA}; spec §7 item 10):"
    )
    by_arm = {triple.arm: triple for triple in triples}
    semantic, precondition = by_arm.get(Arm.SEMANTIC), by_arm.get(Arm.PRECONDITION)
    if semantic is None or precondition is None:
        lines.append("  not computable here: both dispatch arms need a graded episode")
    else:
        wording, verdict = success_rate_wording(semantic.success, precondition.success)
        lines.append(f'  arm 2 vs arm 3 success rates are a "{wording}" by this test')
        if verdict is None:
            lines.append("  no test ran: an arm has no graded episode to take a rate over")
        else:
            lines.append(
                f"  difference={verdict.difference:+.3f}"
                f" {1 - 2 * verdict.alpha:.0%} interval"
                f" [{verdict.interval.low:+.3f}, {verdict.interval.high:+.3f}]"
                f" p_lower={verdict.p_lower:.3f} p_upper={verdict.p_upper:.3f}"
            )
            lines.append(f"  {verdict.reason}")
    return lines


def _mismatch_lines(comparison: MismatchComparison) -> list[str]:
    """The demo mismatch comparison at matched N, and where the figures are."""
    lines: list[str] = []
    lines += [
        "",
        f"Mismatch comparison (arm 2 vs arm 3, matched N={comparison.matched_n}, "
        "variant occurrences only -- the independent ones):",
    ]
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
    return lines


def write_report(ledger: Path, dest: Path) -> Path:
    """Emit the tables and figures into `dest` for the README to embed.

    Writes `ablation_table.csv`, `cost_curve.csv`, `mismatch_comparison.csv` and
    `arm_triples.csv` (the numbers, each rate and each mean beside its denominator),
    `cost_curve.png`, `mismatch_comparison.png` and `pareto.png` (renderings of those
    numbers) and `report.txt`
    (the caveats, the invalid rate, the occurrences each figure used, the change surface
    each fault's rows applied -- plus any disagreement between rows of one fault -- and the
    plain statement that the primary pre-registered analysis is not here).
    Returns `dest`.
    """
    rows = ablation_table(ledger)
    points = cost_curve(ledger)
    comparison = mismatch_comparison(ledger)
    counts = occurrence_counts(ledger)
    triples = arm_triples(ledger)
    pareto = pareto_frontier(triples)
    surfaces = change_surfaces(ledger)
    instances = achieved_instances(ledger)

    dest.mkdir(parents=True, exist_ok=True)
    _write_ablation_csv(dest / "ablation_table.csv", rows)
    _write_cost_csv(dest / "cost_curve.csv", points)
    _write_mismatch_csv(dest / "mismatch_comparison.csv", comparison)
    _write_triple_csv(dest / "arm_triples.csv", triples, pareto)
    _plot_cost_curve(points, dest / "cost_curve.png")
    _plot_mismatch_comparison(comparison, dest / "mismatch_comparison.png")
    _plot_pareto(triples, pareto, dest / "pareto.png")
    (dest / "report.txt").write_text(
        _summary(rows, points, comparison, counts, triples, pareto, surfaces, instances),
        encoding="utf-8",
    )
    return dest
