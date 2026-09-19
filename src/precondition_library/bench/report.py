"""Turn the ledger into the ablation table and the two demo figures.

What is primary, and what this module is not
--------------------------------------------
The pre-registered primary metric (spec §7, "Pre-registered analysis", revised
2026-09-13 before any data existed) is the **mismatch-versus-coverage curve at
matched coverage**, computed over labelled (repo-state, candidate-program)
dispatch pairs -- the seam in `bench.pairs` and the threshold sweep in issue #5.
This module does not compute it, and no number printed here is that measurement.

The episode loop `bench.run` writes is retained only as a demonstration and is
explicitly underpowered. The nominal grid is 5 faults x 4 occurrences x 3 arms,
but only two of the five faults are measurable -- the other three are fixed
single sentences and sit in `tasks.registry.EXCLUDED_FROM_BENCHMARK` -- so the
runnable demo is 2 faults x 4 occurrences x 3 arms = **24 episodes**, and
`bench.run` refuses the excluded three rather than skipping them. Spec §7
excludes the demo from the primary claim. So the two figures built here are:

* a **cost model** -- mean tokens and LLM calls per episode against
  `occurrence_index`, one series per arm, over the **replay** occurrences: the
  later sightings of a state, which are the only occurrences where a library
  could have had something to answer with, and therefore the only place the
  curve can bend. Secondary, and reported as a cost model rather than as a
  result; the token curve is not the finding.
* an **episode-level arm 2 vs arm 3 mismatch comparison at matched N** -- the
  demo's comparative number, reported with a Wilson interval over the **variant**
  occurrences: the first sight of each state, the only independent observations
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

import csv
import math
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..program import EpisodeOutcome
from .ledger import Arm, EpisodeRecord, OccurrenceRole, read

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
    spec_gaming: Rate
    """Graded episodes whose resolution reached the expected state by destroying
    recorded state. Derived from the recorded fact (`recorded_state_intact is False`), not
    stored as a verdict, for the reason the module gives above: a stored verdict
    could not sit beside `ground_truth_ok` without the two disagreeing.

    Its own column because it is otherwise invisible: such a row has
    `ground_truth_ok=False` and reads exactly like a resolution that simply failed
    to repair the fault, when the finding is that it repaired it destructively."""
    mean_tokens: Mean
    mean_embedding_tokens: Mean
    """Arm 2's similarity-seam spend, in its own currency. Reported beside the LLM tokens
    rather than inside them, so a reader can see that one arm pays a second bill when the
    seam is an embedding model (issue #104). Always zero while the seam is lexical."""
    mean_embedding_calls: Mean
    mean_uncached_tokens_in: Mean
    """Input tokens billed at the full input rate. Reported beside the cache-read mean
    so a reader can see the split pricing needs, rather than one summed input number
    (issue #8)."""
    mean_cached_tokens_in: Mean
    mean_cache_write_tokens_in: Mean
    mean_llm_calls: Mean
    mean_wall_clock_s: Mean


class CostPoint(BaseModel):
    """One point of the secondary cost model, for one arm at one occurrence.

    `occurrence_role` is always `REPLAY` here, and it is on the point so that a
    reader of the CSV cannot mistake the curve for one over every occurrence.
    """

    arm: Arm
    occurrence_role: OccurrenceRole
    occurrence_index: int
    episodes: int
    mean_tokens: Mean
    mean_cached_tokens_in: Mean
    mean_llm_calls: Mean
    cumulative_tokens: Mean
    """Amortized cost so far: every token this arm spent at occurrence indices up to
    and including this one, divided by the episodes that spent it. This, not
    `mean_tokens`, is what Figure 2 plots -- a per-occurrence mean is a snapshot and
    cannot show a crossover, while a running amortized cost is the quantity Claim 1
    is actually about."""
    cumulative_llm_calls: Mean
    """The same accumulation for LLM calls, the second half of Claim 1."""


class ArmBreakEven(BaseModel):
    """Where an arm's amortized cost first falls to the baseline's or below.

    This is the crossover Figure 2 is read from. `occurrence_index` is None when the
    run cannot show one, and `detail` says which case it is: "the arms share no
    occurrence index" and "it never crossed" are different findings, and collapsing
    them would let an absent comparison read as a passed one.
    """

    arm: Arm
    baseline: Arm
    occurrence_index: int | None
    detail: str


class ArmTriple(BaseModel):
    """One arm's three numbers, each carrying its own denominator.

    What spec §7 item 8 and Claim 1 promise: cost per success beside cost per
    episode, because an arm that succeeds more often may legitimately spend more per
    episode. Pooled over every graded episode of the arm, including the episodes that
    failed -- dropping them would flatter amortization (§7 item 7), and each field
    carries the count it was taken over so a reader can see how much is pooled.

    The cell-level ablation table remains the detail; this is the summary a reader
    compares arms on, and it is deliberately not a row of that table.
    """

    arm: Arm
    graded_episodes: int
    success: Rate
    tokens_per_episode: Mean
    tokens_per_success: Mean
    """Total tokens over the arm's graded episodes, divided by how many of them reached
    the expected state. `n` is that count of successes, so an arm with none reports
    `value=None` with `n=0` -- 0/0 has no value, and 0.0 would read as free."""


class ArmDominance(BaseModel):
    """Which arms beat this one on all three numbers at once."""

    arm: Arm
    dominated_by: list[Arm]


class ParetoFrontier(BaseModel):
    """The triple's Pareto set: the arms nothing else beats on all three at once.

    A dominates B when A's success rate is at least B's and both of A's cost figures
    are at most B's, with at least one of the three strict. `unranked` holds arms with
    no cost-per-success to compare -- they are excluded from dominance rather than
    treated as best or worst, because silently assigning either would invent a
    ranking the run does not support.
    """

    frontier: list[Arm]
    dominated: list[ArmDominance]
    unranked: list[Arm]


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
) -> Equivalence | None:
    """Whether two success rates are equivalent within `margin`, by TOST.

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
            f"+/-{margin:.0%}, so the two success rates are equivalent at this margin"
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


class PromptPrefix(BaseModel):
    """The raw character length of a system prompt the run sends, by phase.

    **Raw** means characters, not tokens: it is a size of the text as written, and it
    is deliberately not presented as a token count, which only the provider can give.
    """

    phase: str
    chars: int
    source: str


def prompt_prefix_lengths() -> list[PromptPrefix]:
    """The two prompt prefixes this repository sends, in raw characters.

    Reported once each rather than per arm, and that is a finding rather than a
    shortcut (issue #8, item 5): both prompts are module-level constants -- one in
    `agents/react.py`, one derived in `agents/compile.py` -- and **all three arms send
    the same ones**. A per-arm column would print the same number three times and imply
    a difference that does not exist. What differs between the arms is how much
    transcript accumulates around the prefix, which the per-episode input tokens carry,
    not the prefix itself.

    The compile prefix is measured with no variant ids named, which is the shortest form
    it takes; naming an intent's declared variants makes it longer by their joined
    length. It is also the only one of the two that is not a fixed constant.
    """
    from ..agents import compile as compile_agent
    from ..agents import react

    return [
        PromptPrefix(
            phase="learn (ReAct)",
            chars=len(react.SYSTEM_PROMPT),
            source="agents/react.py SYSTEM_PROMPT (fixed)",
        ),
        PromptPrefix(
            phase="compile",
            chars=len(compile_agent._system_prompt(None)),
            source="agents/compile.py _system_prompt (grows by the named variant ids)",
        ),
    ]


class ArmMismatch(BaseModel):
    """One arm's side of the matched comparison."""

    arm: Arm
    available: int
    """Graded *variant* episodes this arm has in the ledger, before matching.

    Replays are not in this count. A replay's state was introduced by an earlier
    occurrence and the program that answers it was admitted there, so its
    outcome carries no information the variant did not already carry."""
    matched_n: int
    """Graded variant episodes used; equal across the two arms by construction."""
    mismatch: Rate
    interval: Interval | None


class MismatchComparison(BaseModel):
    """Arm 2 vs arm 3 mismatch at matched N -- the demo's number, not the claim.

    Computed over the variant occurrences, and `occurrence_role` says so on the
    model rather than only in the prose: the independent observations are the
    first sightings of a state, not every episode the run happened to record.
    """

    occurrence_role: OccurrenceRole
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
) -> tuple[list[EpisodeRecord], int, Rate, Rate, Rate, Rate, Mean, Mean, Mean, Mean, Mean, Mean]:
    """The shared arithmetic for one cell: graded rows, counts, rates and means."""
    graded = _graded(group)
    return (
        graded,
        len(group),
        Rate(numerator=len(group) - len(graded), denominator=len(group)),
        Rate(numerator=sum(1 for r in graded if r.succeeded), denominator=len(graded)),
        Rate(numerator=sum(1 for r in graded if r.misfired), denominator=len(graded)),
        # `is False`, not falsy: None means the check did not run, and counting it
        # would report every pre-check row as spec-gaming.
        Rate(
            numerator=sum(1 for r in graded if r.recorded_state_intact is False),
            denominator=len(graded),
        ),
        _mean(r.tokens_in + r.tokens_out for r in graded),
        _mean(r.uncached_tokens_in for r in graded),
        _mean(r.cached_tokens_in for r in graded),
        _mean(r.cache_write_tokens_in for r in graded),
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
        computed = _rows(group)
        graded, episodes = computed[0], computed[1]
        invalid, success, mismatch, gaming = computed[2:6]
        tokens, uncached, cached, write, calls, wall = computed[6:]
        # Computed here rather than added to `_rows`' result: that tuple already carries
        # twelve positional values, and two more for a currency only arm 2 spends is the
        # kind of thing that gets unpacked in the wrong order.
        embedding = _mean(r.embedding_tokens for r in graded)
        embedding_calls = _mean(r.embedding_calls for r in graded)
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
                spec_gaming=gaming,
                mean_tokens=tokens,
                mean_embedding_tokens=embedding,
                mean_embedding_calls=embedding_calls,
                mean_uncached_tokens_in=uncached,
                mean_cached_tokens_in=cached,
                mean_cache_write_tokens_in=write,
                mean_llm_calls=calls,
                mean_wall_clock_s=wall,
            )
        )
    return rows


def cost_curve(ledger: Path) -> list[CostPoint]:
    """Figure 2. Cumulative amortized tokens and calls per episode, per arm.

    Each point carries an accumulating series as well as its own occurrence's mean.
    The accumulation is what the figure plots, because a per-occurrence mean is a
    snapshot: it says what this occurrence cost, not whether the arm has yet paid
    back what compiling cost it, so no crossover can be read off it (issue #8).

    Computed over the **replay** occurrences and no others. A variant occurrence
    is the first sight of its state, so no program admitted from that state can
    exist yet and the episode pays the full price of solving it: the learning
    pass, not the amortized one. The curve is the accumulation's effect, and it
    can only bend on occurrences the library could answer -- which is exactly the
    replays. Arm 1 pays full price on the same occurrence indices because it has
    no library, and that contrast is what the figure is for.

    Because compile cost is charged to occurrence 1 (spec §7), an arm that compiles
    starts the accumulation above the baseline and can only cross it later, or not
    at all. That crossing, or its absence, is the result -- see `break_even`.

    A ledger with no replay occurrence yields no points and the report says so.
    That is not the same as a curve of zero: it means the run never revisited a
    state, so nothing about amortization can be read off it.

    A secondary cost model, not a result. Grouping is by (arm, occurrence_index)
    and never merges arms: the comparison of the accumulations is the only thing
    the curve is for, and pooling two arms would erase it. Invalid episodes are
    excluded from the curve as they are from every metric denominator; their
    spend, which is real when the checker raised after the arm ran, is on the
    ledger rows themselves rather than averaged in here.
    """
    groups: dict[tuple[Arm, int], list[EpisodeRecord]] = {}
    for record in _graded(read(ledger)):
        if record.occurrence_role is not OccurrenceRole.REPLAY:
            continue
        key = (record.arm, record.occurrence_index)
        groups.setdefault(key, []).append(record)

    points: list[CostPoint] = []
    running_tokens: dict[Arm, list[float]] = {}
    running_calls: dict[Arm, list[float]] = {}
    # Sorted by (arm, occurrence_index), so each arm's running series is extended in
    # ascending occurrence order and every point accumulates only its own past.
    for key in sorted(groups, key=lambda k: (k[0].value, k[1])):
        arm, occurrence = key
        group = groups[key]
        running_tokens.setdefault(arm, []).extend(float(r.tokens_in + r.tokens_out) for r in group)
        running_calls.setdefault(arm, []).extend(float(r.llm_calls) for r in group)
        points.append(
            CostPoint(
                arm=arm,
                occurrence_role=OccurrenceRole.REPLAY,
                occurrence_index=occurrence,
                episodes=len(group),
                mean_tokens=_mean(r.tokens_in + r.tokens_out for r in group),
                mean_cached_tokens_in=_mean(r.cached_tokens_in for r in group),
                mean_llm_calls=_mean(r.llm_calls for r in group),
                cumulative_tokens=_mean(running_tokens[arm]),
                cumulative_llm_calls=_mean(running_calls[arm]),
            )
        )
    return points


def break_even(points: list[CostPoint], baseline: Arm = Arm.REACT) -> list[ArmBreakEven]:
    """Where each arm's amortized cost first falls to `baseline`'s, or why not.

    Compared only at occurrence indices both arms have, so the crossing is a
    like-for-like comparison rather than one arm's early occurrences against
    another's late ones -- which would find a crossover that the run does not
    support. An arm with no shared index, or one that never crosses, reports None
    with the reason rather than being dropped; a missing comparison must not read
    as a result.
    """
    by_arm: dict[Arm, dict[int, CostPoint]] = {}
    for point in points:
        by_arm.setdefault(point.arm, {})[point.occurrence_index] = point

    baseline_points = by_arm.get(baseline, {})
    others = sorted(
        (candidate for candidate in by_arm if candidate is not baseline),
        key=lambda candidate: candidate.value,
    )
    if not baseline_points:
        # A distinct finding from "no shared index": here the baseline arm is absent
        # from the ledger entirely, so no index could ever be shared.
        return [
            ArmBreakEven(
                arm=arm,
                baseline=baseline,
                occurrence_index=None,
                detail=(
                    f"{baseline.value} has no replay occurrence in this ledger, so there is "
                    f"nothing to compare {arm.value} against"
                ),
            )
            for arm in others
        ]

    findings: list[ArmBreakEven] = []
    for arm in others:
        series = by_arm[arm]
        shared = sorted(set(series) & set(baseline_points))
        if not shared:
            findings.append(
                ArmBreakEven(
                    arm=arm,
                    baseline=baseline,
                    occurrence_index=None,
                    detail=(
                        f"{arm.value} and {baseline.value} share no occurrence index, so no "
                        f"crossover is computable from this ledger"
                    ),
                )
            )
            continue

        crossed: int | None = None
        for index in shared:
            mine = series[index].cumulative_tokens.value
            theirs = baseline_points[index].cumulative_tokens.value
            if mine is not None and theirs is not None and mine <= theirs:
                crossed = index
                break

        if crossed is None:
            detail = (
                f"{arm.value}'s amortized cost never reached {baseline.value}'s over the "
                f"shared occurrence indices {shared}: no break-even in this run"
            )
        else:
            detail = (
                f"{arm.value}'s amortized cost first reached {baseline.value}'s at "
                f"occurrence {crossed}"
            )
        findings.append(
            ArmBreakEven(arm=arm, baseline=baseline, occurrence_index=crossed, detail=detail)
        )
    return findings


def occurrence_counts(ledger: Path) -> dict[OccurrenceRole, int]:
    """How many graded rows of each role the ledger holds.

    Reported so a reader can see what each figure left out. Invalid episodes are
    excluded, as they are from every metric denominator.
    """
    counts = {role: 0 for role in OccurrenceRole}
    for record in _graded(read(ledger)):
        counts[record.occurrence_role] += 1
    return counts


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


def _comparison_note(
    matched_n: int,
    semantic_available: int,
    precondition_available: int,
    replays_excluded: int,
) -> str:
    parts = [
        "Episode-level demo, not the pre-registered analysis: the primary metric is "
        "mismatch vs coverage at matched coverage over labelled dispatch pairs (spec "
        "§7), the episode loop is underpowered, and it is excluded from that claim.",
        "Computed over the variant occurrences only -- the first sight of each state, "
        "which are the independent observations. Replay occurrences are excluded "
        f"({replays_excluded} graded row(s) in this ledger): a replay's state was "
        "introduced by an earlier occurrence and the program answering it was admitted "
        "there, so counting it would count that one observation again.",
        f"Matched N={matched_n} (arm 2 has {semantic_available} graded variant episode(s), "
        f"arm 3 {precondition_available}); any episode outside a common stratum is "
        "reported in `available`, not dropped silently.",
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

    Computed over the **variant** occurrences and no others. A replay occurrence
    re-asks a state an earlier episode already saw, and the program that answers
    it -- correctly or not -- was admitted by that episode, so its mismatch is
    that program's error counted a second time. An interval over every row would
    therefore be narrower than the evidence, which is the one direction an
    underpowered demo must not fail in.
    """
    graded = _graded(read(ledger))
    records = [record for record in graded if record.occurrence_role is OccurrenceRole.VARIANT]
    replays_excluded = sum(
        1 for record in graded if record.occurrence_role is OccurrenceRole.REPLAY
    )
    semantic = [record for record in records if record.arm is Arm.SEMANTIC]
    precondition = [record for record in records if record.arm is Arm.PRECONDITION]
    matched_semantic, matched_precondition = _match_strata(semantic, precondition)
    matched_n = len(matched_semantic)
    return MismatchComparison(
        occurrence_role=OccurrenceRole.VARIANT,
        matched_n=matched_n,
        semantic=_arm_mismatch(Arm.SEMANTIC, semantic, matched_semantic),
        precondition=_arm_mismatch(Arm.PRECONDITION, precondition, matched_precondition),
        note=_comparison_note(matched_n, len(semantic), len(precondition), replays_excluded),
    )


def _overall_invalid(rows: list[AblationRow]) -> Rate:
    return Rate(
        numerator=sum(row.invalid.numerator for row in rows),
        denominator=sum(row.episodes for row in rows),
    )


def _overall_spec_gaming(rows: list[AblationRow]) -> Rate:
    """Pooled spec-gaming rate over the graded episodes of every cell.

    Pooling the counts is safe where pooling the cells' *means* would not be: this is
    a plain count over a plain count, so the denominator is exactly the episodes it
    speaks for. The ablation table still carries no total row, for the reason its
    docstring gives -- but a total is what an alarm needs, and this one is flagged in
    the summary rather than added as a row.
    """
    return Rate(
        numerator=sum(row.spec_gaming.numerator for row in rows),
        denominator=sum(row.graded_episodes for row in rows),
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


def arm_triples(ledger: Path) -> list[ArmTriple]:
    """Success rate, tokens per episode, and tokens per success -- one row per arm.

    Pooled over every graded episode, both roles. Success rate belongs in the triple
    without the role split: it is the proportion of episodes the arm handled, and
    restricting it to the replays would exclude exactly the learning pass that decides
    whether an arm pays off. The role split stays visible in the cell table.
    """
    groups: dict[Arm, list[EpisodeRecord]] = {}
    for record in _graded(read(ledger)):
        groups.setdefault(record.arm, []).append(record)

    triples: list[ArmTriple] = []
    for arm in sorted(groups, key=lambda candidate: candidate.value):
        records = groups[arm]
        successes = [r for r in records if r.succeeded]
        tokens = [r.tokens_in + r.tokens_out for r in records]
        # `_mean` over the successes only cannot express this: it would be the mean
        # cost of a successful episode, not the arm's cost divided by its successes
        # (which is what "cost per success" means, and what makes a cheap arm that
        # rarely succeeds look as bad as it is).
        if successes:
            per_success = Mean(n=len(successes), value=sum(tokens) / len(successes))
        else:
            per_success = Mean(n=0, value=None)
        triples.append(
            ArmTriple(
                arm=arm,
                graded_episodes=len(records),
                success=Rate(numerator=len(successes), denominator=len(records)),
                tokens_per_episode=_mean(tokens),
                tokens_per_success=per_success,
            )
        )
    return triples


def pareto_frontier(triples: list[ArmTriple]) -> ParetoFrontier:
    """Which arms nothing else beats on success, tokens per episode and per success.

    The three are reported together because they trade off: an arm that spends fewer
    tokens per episode by attempting less will lose on success rate, and one that
    succeeds more by retrying will lose on cost. An arm is only credited with
    dominating another if it is no worse on *all three*, so the frontier is the honest
    summary of which arms a reader should still be choosing between.
    """
    ranked = [t for t in triples if t.tokens_per_success.value is not None]
    unranked = [t.arm for t in triples if t.tokens_per_success.value is None]

    def dominates(better: ArmTriple, worse: ArmTriple) -> bool:
        assert better.success.value is not None and worse.success.value is not None
        assert better.tokens_per_success.value is not None
        assert worse.tokens_per_success.value is not None
        assert better.tokens_per_episode.value is not None
        assert worse.tokens_per_episode.value is not None
        no_worse = (
            better.success.value >= worse.success.value
            and better.tokens_per_episode.value <= worse.tokens_per_episode.value
            and better.tokens_per_success.value <= worse.tokens_per_success.value
        )
        strict = (
            better.success.value > worse.success.value
            or better.tokens_per_episode.value < worse.tokens_per_episode.value
            or better.tokens_per_success.value < worse.tokens_per_success.value
        )
        return no_worse and strict

    dominated = [
        ArmDominance(
            arm=candidate.arm,
            dominated_by=[
                other.arm
                for other in ranked
                if other.arm is not candidate.arm and dominates(other, candidate)
            ],
        )
        for candidate in ranked
    ]
    return ParetoFrontier(
        frontier=[d.arm for d in dominated if not d.dominated_by],
        dominated=[d for d in dominated if d.dominated_by],
        unranked=unranked,
    )


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


def _summary(
    rows: list[AblationRow],
    points: list[CostPoint],
    comparison: MismatchComparison,
    counts: dict[OccurrenceRole, int],
    triples: list[ArmTriple],
    pareto: ParetoFrontier,
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
        "Occurrences by role (graded rows): "
        f"{OccurrenceRole.VARIANT.value}={counts[OccurrenceRole.VARIANT]} "
        f"{OccurrenceRole.REPLAY.value}={counts[OccurrenceRole.REPLAY]}. A variant is the "
        "first sight of",
        "a state and is the only kind of independent observation; a replay revisits a state an",
        "earlier occurrence introduced. The cost curve uses the replays, the mismatch comparison",
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
    lines.append(
        "Pareto over the three (an arm is only dominated if it is no better on success "
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
                f" {_format_mean(row.mean_embedding_calls, 'seam calls')}"
            )
    if not any(row.mean_embedding_tokens.value for row in rows):
        lines.append("  0: the seam is lexical and spends nothing, so no arm pays a second bill")
    lines.append(
        "Prompt prefixes the run sends (raw characters, shared by every arm -- the "
        "per-arm difference is transcript growth around the prefix, not the prefix):"
    )
    for prefix in prompt_prefix_lengths():
        lines.append(f"  {prefix.phase}: {prefix.chars:,} chars -- {prefix.source}")
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
    return "\n".join(lines)


def write_report(ledger: Path, dest: Path) -> Path:
    """Emit the tables and figures into `dest` for the README to embed.

    Writes `ablation_table.csv`, `cost_curve.csv`, `mismatch_comparison.csv` and
    `arm_triples.csv` (the numbers, each rate and each mean beside its denominator),
    `cost_curve.png`, `mismatch_comparison.png` and `pareto.png` (renderings of those
    numbers) and `report.txt`
    (the caveats, the invalid rate, the occurrences each figure used, and the
    plain statement that the primary pre-registered analysis is not here).
    Returns `dest`.
    """
    rows = ablation_table(ledger)
    points = cost_curve(ledger)
    comparison = mismatch_comparison(ledger)
    counts = occurrence_counts(ledger)
    triples = arm_triples(ledger)
    pareto = pareto_frontier(triples)

    dest.mkdir(parents=True, exist_ok=True)
    _write_ablation_csv(dest / "ablation_table.csv", rows)
    _write_cost_csv(dest / "cost_curve.csv", points)
    _write_mismatch_csv(dest / "mismatch_comparison.csv", comparison)
    _write_triple_csv(dest / "arm_triples.csv", triples, pareto)
    _plot_cost_curve(points, dest / "cost_curve.png")
    _plot_mismatch_comparison(comparison, dest / "mismatch_comparison.png")
    _plot_pareto(triples, pareto, dest / "pareto.png")
    (dest / "report.txt").write_text(
        _summary(rows, points, comparison, counts, triples, pareto), encoding="utf-8"
    )
    return dest
