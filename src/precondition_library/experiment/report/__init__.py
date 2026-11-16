"""Turn the ledger into the ablation table and the two demo figures.

What is primary, and what this module is not
--------------------------------------------
The pre-registered primary metric (spec §7, "Pre-registered analysis", revised
2026-09-13 before any data existed) is the **mismatch-versus-coverage curve at
matched coverage**, computed over labelled (repo-state, candidate-program)
dispatch pairs -- the seam in `bench.pairs`, swept and matched in `bench.coverage`
(issue #5, ADR-0008). This module does not compute it, and no number printed here
is that measurement.

The episode loop `bench.run` writes is retained only as a demonstration and is
explicitly underpowered. The nominal grid is 5 faults x 4 occurrences x 3 arms,
and since ADR-0029 every fault is measurable -- `tasks.registry.EXCLUDED_FROM_BENCHMARK`
is empty, and `bench.run` would refuse a fault listed there rather than skip it -- so the
runnable demo is the whole **60 episodes**. The issue #7 baselines are additional arms a
run may include -- among them the zero-token gold **oracle floor** -- so a run that
names them adds 5 x 4 episodes per baseline on the same
grid; the per-arm tables below carry each one without special-casing. Spec §7
excludes the demo from the primary claim. So the two figures built here are:

* a **cost model** -- mean tokens and LLM calls per episode against
  `occurrence_index`, one series per arm, over the **replay** occurrences: the
  later sightings of an instance, which are the only occurrences where a library
  could have had something to answer with, and therefore the only place the
  curve can bend. Secondary, and reported as a cost model rather than as a
  result; the token curve is not the finding.
* an **episode-level arm 2 vs arm 3 mismatch comparison at matched N** -- the
  demo's comparative number, reported with a Wilson interval over the **variant**
  occurrences: the first sight of each instance, the only independent observations
  in the ledger. Not the pre-registered claim, and its note says so in the
  output.

The two figures take different occurrences on purpose, and each says which it
used. A replay's state was introduced by an earlier episode and the program that
answers it was admitted there, so counting a replay in the mismatch comparison
counts one observation twice; a variant is the learning pass, before anything
could be replayed, so a cost curve drawn over variants cannot bend. Spec §7's
"Ledger" and "Figures" are the source for the rule; `bench.splits` declares it.

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

from precondition_library.experiment.report.bootstrap import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    ClusterBootstrap,
    _instance_key,
    _per_fire,
    cluster_bootstrap,
    read_replicates,
)
from precondition_library.experiment.report.floor import (
    ARM2_CANDIDATES_PER_DECISION,
    BaselineFloor,
    arm2_baseline_floor,
)
from precondition_library.experiment.report.render import (
    _ablation_lines,
    _cell,
    _cost_curve_lines,
    _equivalence_lines,
    _format_mean,
    _format_rate,
    _format_surface,
    _header_lines,
    _instance_lines,
    _mismatch_lines,
    _pareto_lines,
    _plot_cost_curve,
    _plot_mismatch_comparison,
    _plot_pareto,
    _prefix_lines,
    _pyplot,
    _seam_lines,
    _summary,
    _surface_lines,
    _triple_lines,
    _write_ablation_csv,
    _write_cost_csv,
    _write_csv,
    _write_mismatch_csv,
    _write_triple_csv,
    write_report,
)
from precondition_library.experiment.report.stats import (
    EQUIVALENCE_MARGIN,
    INVALID_RATE_ALARM,
    SMALL_SAMPLE_N,
    TOST_ALPHA,
    Z_95,
    Equivalence,
    Interval,
    Mean,
    Rate,
    _adjusted_variance,
    _mean,
    _phi,
    success_rate_wording,
    tost_equivalence,
    wilson_interval,
)
from precondition_library.experiment.report.tables import (
    AblationRow,
    AchievedInstance,
    AppliedSurface,
    ArmBreakEven,
    ArmDominance,
    ArmMismatch,
    ArmTriple,
    CostPoint,
    FactorialCell,
    FaultSurface,
    MismatchComparison,
    ParetoFrontier,
    PromptPrefix,
    _arm_mismatch,
    _by_seed,
    _comparison_note,
    _graded,
    _match_strata,
    _overall_invalid,
    _overall_spec_gaming,
    _rows,
    ablation_table,
    achieved_instances,
    admission_factorial,
    arm_triples,
    break_even,
    change_surfaces,
    cost_curve,
    mismatch_comparison,
    occurrence_counts,
    pareto_frontier,
    prompt_prefix_lengths,
)

__all__ = [
    "ARM2_CANDIDATES_PER_DECISION",
    "AblationRow",
    "AchievedInstance",
    "AppliedSurface",
    "ArmBreakEven",
    "ArmDominance",
    "ArmMismatch",
    "ArmTriple",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "BaselineFloor",
    "ClusterBootstrap",
    "CostPoint",
    "EQUIVALENCE_MARGIN",
    "Equivalence",
    "FactorialCell",
    "FaultSurface",
    "INVALID_RATE_ALARM",
    "Interval",
    "Mean",
    "MismatchComparison",
    "ParetoFrontier",
    "PromptPrefix",
    "Rate",
    "SMALL_SAMPLE_N",
    "TOST_ALPHA",
    "Z_95",
    "_ablation_lines",
    "_adjusted_variance",
    "_arm_mismatch",
    "_by_seed",
    "_cell",
    "_comparison_note",
    "_cost_curve_lines",
    "_equivalence_lines",
    "_format_mean",
    "_format_rate",
    "_format_surface",
    "_graded",
    "_header_lines",
    "_instance_key",
    "_instance_lines",
    "_match_strata",
    "_mean",
    "_mismatch_lines",
    "_overall_invalid",
    "_overall_spec_gaming",
    "_pareto_lines",
    "_per_fire",
    "_phi",
    "_plot_cost_curve",
    "_plot_mismatch_comparison",
    "_plot_pareto",
    "_prefix_lines",
    "_pyplot",
    "_rows",
    "_seam_lines",
    "_summary",
    "_surface_lines",
    "_triple_lines",
    "_write_ablation_csv",
    "_write_cost_csv",
    "_write_csv",
    "_write_mismatch_csv",
    "_write_triple_csv",
    "ablation_table",
    "achieved_instances",
    "admission_factorial",
    "arm2_baseline_floor",
    "arm_triples",
    "break_even",
    "change_surfaces",
    "cluster_bootstrap",
    "cost_curve",
    "mismatch_comparison",
    "occurrence_counts",
    "pareto_frontier",
    "prompt_prefix_lengths",
    "read_replicates",
    "success_rate_wording",
    "tost_equivalence",
    "wilson_interval",
    "write_report",
]
