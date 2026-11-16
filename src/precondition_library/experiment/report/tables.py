"""The ledger read into the report's tables: ablation rows, cost curve, mismatch, factorial."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from precondition_library.experiment.ledger import Arm, EpisodeRecord, OccurrenceRole, read
from precondition_library.experiment.report.stats import SMALL_SAMPLE_N, Interval, Mean, Rate, _mean
from precondition_library.program import EpisodeOutcome


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
    from precondition_library.agents import compile as compile_agent
    from precondition_library.agents import react

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
    first sightings of an instance, not every episode the run happened to record.
    """

    occurrence_role: OccurrenceRole
    matched_n: int
    semantic: ArmMismatch
    precondition: ArmMismatch
    note: str


class AppliedSurface(BaseModel):
    """One change surface that rows of a fault actually applied (issue #96)."""

    surface: tuple[str, ...]
    episodes: int
    """Rows that applied exactly this surface. Empty is a real value here, not a
    placeholder: an empty declaration that was applied is the strictest one."""


class FaultSurface(BaseModel):
    """What one fault's rows claimed a resolution needed, read from the ledger (#96).

    Derived from the recorded `change_surface` field, never from `FaultSpec.change_surface`,
    because spec-gaming is derived from `recorded_state_intact(..., surface=...)`: the verdict
    a row carries depends on the surface that was *applied*. A report regenerated from an
    older ledger that read the current registry would print a declaration that run never
    used -- the drift this repository's rules about records exist to prevent.

    `surfaces` holds only the non-`None` applied values. A `None` row means the check did
    not run (an invalid episode, or a fault-level failure before the surface was reached), so
    it is no evidence about the declaration and cannot create a disagreement by itself.
    """

    fault_type: str
    episodes: int
    """Every row for this fault, applied or not -- the denominator `applied` is read
    against, so a fault no row checked stays visible rather than absent."""
    applied: int
    """Rows whose resolution was checked against a declared surface. These are the rows
    the report's surface section is based on."""
    surfaces: list[AppliedSurface]
    """The distinct applied surfaces, sorted, each with its row count. Empty when no row
    applied one."""
    disagreement: bool
    """True when two or more *different* non-`None` surfaces were applied by rows of this
    fault: a real inconsistency in the run, named in the report rather than resolved by
    silently picking one. A `None` row is not evidence and cannot set this."""


class AchievedInstance(BaseModel):
    """One (fault, resolution) cell's independent environments (ADR-0005 decision 8).

    The number of independent observations a resolution's seeds support is the
    number of distinct **instances** they build, not the number of seeds. Carried
    per resolution so a reader cannot take a larger seed count for more power:
    three hundred seeds that draw one instance are one observation.
    """

    fault_type: str
    resolution: str
    seeds: int
    """Distinct seeds this run gave the resolution."""
    instances: int
    """Distinct instance identities those seeds build (`instance_for_seed`)."""


def achieved_instances(ledger: Path) -> list[AchievedInstance]:
    """Per (fault, resolution), the independent environments this run's seeds build.

    ADR-0005 decision 8. The ledger supplies *which* seeds ran -- it is the record
    of the run -- and `FaultSpec.instance_for_seed` supplies each seed's instance
    identity, so the count is the environment count and not the seed count. Grouped
    by the resolution the ledger recorded (`correct_variant`), not by re-deriving
    it from today's injector, so a report regenerated from an older ledger groups
    on the label that run actually used.

    Rows with no recorded resolution (an invalid episode, or a fault with no
    ambiguous intent) are skipped: they are no evidence about an environment. A
    ledger with no measurable rows yields an empty list and the report says so.
    """
    from precondition_library.tasks.faults import FAULTS

    instances: dict[tuple[str, str], set[str]] = {}
    seeds: dict[tuple[str, str], set[int]] = {}
    for record in read(ledger):
        if record.correct_variant is None:
            continue
        spec = FAULTS.get(record.fault_type)
        if spec is None:
            continue
        instance = spec.instance_for_seed(record.seed)
        if instance is None:
            continue
        key = (record.fault_type, record.correct_variant)
        instances.setdefault(key, set()).add(instance)
        seeds.setdefault(key, set()).add(record.seed)
    return [
        AchievedInstance(
            fault_type=fault_type,
            resolution=resolution,
            seeds=len(seeds[(fault_type, resolution)]),
            instances=len(instances[(fault_type, resolution)]),
        )
        for (fault_type, resolution) in sorted(instances)
    ]


def _graded(records: Iterable[EpisodeRecord]) -> list[EpisodeRecord]:
    """Every episode that actually ran. Invalid rows are accounted for elsewhere."""
    return [record for record in records if record.outcome is not EpisodeOutcome.INVALID]


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
    is the first sight of its instance, so no program admitted from that state can
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


def change_surfaces(ledger: Path) -> list[FaultSurface]:
    """The change surface each fault's rows applied, per fault, from the ledger (#96).

    Grouped by fault over every row, invalid ones included: they carry no surface, so they
    contribute to `episodes` -- the denominator -- and never to `applied`. Surfaces are
    sorted so the report is deterministic, and a fault whose rows applied two different
    non-`None` surfaces is flagged rather than having one chosen for it, because that is
    the run disagreeing with itself and the reader has to be told which ways it disagreed.

    The registry is deliberately not consulted. Reading `FaultSpec.change_surface` here
    would be cheaper and would make the section describe today's declaration instead of the
    surface this run graded against -- the two differ the moment the declaration changes,
    and spec-gaming is derived from the second.
    """
    groups: dict[str, list[EpisodeRecord]] = {}
    for record in read(ledger):
        groups.setdefault(record.fault_type, []).append(record)

    findings: list[FaultSurface] = []
    for fault_type in sorted(groups):
        group = groups[fault_type]
        counted: dict[tuple[str, ...], int] = {}
        for record in group:
            if record.change_surface is None:
                # Not applied, so not evidence about any declaration: it must not appear
                # in `surfaces` and must not count toward a disagreement.
                continue
            counted[record.change_surface] = counted.get(record.change_surface, 0) + 1
        surfaces = [
            AppliedSurface(surface=surface, episodes=count)
            for surface, count in sorted(counted.items())
        ]
        findings.append(
            FaultSurface(
                fault_type=fault_type,
                episodes=len(group),
                applied=sum(applied.episodes for applied in surfaces),
                surfaces=surfaces,
                disagreement=len(surfaces) > 1,
            )
        )
    return findings


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
        "Computed over the variant occurrences only -- the first sight of each instance, "
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


class FactorialCell(BaseModel):
    """One cell of the {dispatch} x {admission} 2x2 (Figure 3, issue #4, ADR-0010)."""

    arm: Arm
    admission_gate: str
    library_hash: str | None
    """The one frozen library this cell dispatched against; a cell is one library."""
    episodes: int
    """Graded variant episodes, the independent observations (ADR-0005)."""
    coverage: Rate
    """Fires over episodes."""
    mismatch: Rate
    """Wrong fires over fires -- per fire, as ADR-0008 defines mismatch."""


def admission_factorial(ledger: Path) -> list[FactorialCell]:
    """Figure 3: dispatch x admission, one cell per (arm, gate), over variant episodes.

    Separates the negative-sandbox criterion (Claim 3, the admission factor) from
    predicate dispatch (Claim 2, the dispatch factor). The rows come from frozen runs
    against the two libraries `bench.build_library` gates from one compile; a cell
    refuses rows it cannot interpret rather than pooling them:

    * a dispatch-arm row with no `admission_gate` -- a frozen library without a build
      manifest -- is an unknown gate, not a guess at one;
    * a gate whose rows span more than one `library_hash` is not one library, so the
      two dispatch arms in it did not face the same programs: per-arm online
      libraries, or two builds mixed into one ledger.
    """
    rows = [
        record
        for record in _graded(read(ledger))
        if record.arm in (Arm.SEMANTIC, Arm.PRECONDITION)
        and record.occurrence_role is OccurrenceRole.VARIANT
    ]
    unknown = [record for record in rows if record.admission_gate is None]
    if unknown:
        raise ValueError(
            f"{len(unknown)} dispatch row(s) have no admission gate; a frozen library needs "
            f"its build manifest for its rows to enter the admission factorial"
        )
    cells: list[FactorialCell] = []
    for gate in sorted({record.admission_gate for record in rows if record.admission_gate}):
        in_gate = [record for record in rows if record.admission_gate == gate]
        hashes = {record.library_hash for record in in_gate}
        if len(hashes) > 1:
            raise ValueError(
                f"the {gate!r} rows span {len(hashes)} libraries; each admission condition "
                f"must be one frozen library that both dispatch arms ran against (issue #4)"
            )
        for arm in (Arm.SEMANTIC, Arm.PRECONDITION):
            cell = [record for record in in_gate if record.arm is arm]
            if not cell:
                continue
            fires = [record for record in cell if record.fired_variant is not None]
            cells.append(
                FactorialCell(
                    arm=arm,
                    admission_gate=gate,
                    library_hash=next(iter(hashes)),
                    episodes=len(cell),
                    coverage=Rate(numerator=len(fires), denominator=len(cell)),
                    mismatch=Rate(
                        numerator=sum(record.misfired for record in fires),
                        denominator=len(fires),
                    ),
                )
            )
    return cells


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
