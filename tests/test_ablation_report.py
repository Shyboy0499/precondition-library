"""The report's arithmetic, its denominators, and the quadrants it must not lose.

These build ledgers with `ledger.append` into `tmp_path` and never run an
episode, so the suite stays fast. The numbers below are chosen to be verifiable
by eye: a group of two episodes with tokens 10 and 20 has mean 15, and no test
has to re-derive the implementation to know that.

Three properties carry the file, each from a defect the design guards against:

* a rate without its denominator (the pre-registration's denominator rule);
* an `invalid` episode dropped from the metrics *or* hidden from the reader --
  both are failures, so both halves are asserted;
* `misfired` and `succeeded` treated as exclusive -- a wrong fire can still end
  successfully through the fallback, and that quadrant is why the ledger was
  reshaped to derive the verdicts instead of storing one outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import GIT_STATUS_AT_IMPORT, git_status_porcelain, make_record

from precondition_library.bench.ledger import Arm, EpisodeRecord, OccurrenceRole, append
from precondition_library.bench.report import (
    EQUIVALENCE_MARGIN,
    SMALL_SAMPLE_N,
    Mean,
    Rate,
    ablation_table,
    arm_triples,
    break_even,
    cost_curve,
    mismatch_comparison,
    pareto_frontier,
    prompt_prefix_lengths,
    success_rate_wording,
    tost_equivalence,
    wilson_interval,
    write_report,
)
from precondition_library.program import EpisodeOutcome

ROOT = Path(__file__).resolve().parents[1]


def _record(**overrides) -> EpisodeRecord:
    """This module's baseline: arm 2, a successful *variant* episode.

    A caller's own `arm`/`outcome` still win, because the baseline is set with
    `setdefault` rather than passed alongside them. Variant is the baseline
    because it is the role the mismatch comparison reads; a test about the cost
    curve says `_replay` instead, so neither figure can be fed the other's
    occurrences by accident.
    """
    overrides.setdefault("arm", Arm.SEMANTIC)
    overrides.setdefault("outcome", EpisodeOutcome.SUCCESS)
    return make_record(**overrides)


def _replay(**overrides) -> EpisodeRecord:
    """The same baseline, labelled as a later sight of a state."""
    overrides["occurrence_role"] = OccurrenceRole.REPLAY
    return _record(**overrides)


def _write(path: Path, records: list[EpisodeRecord]) -> Path:
    for record in records:
        append(path, record)
    return path


def _bench_entries() -> set[str]:
    """Every path under the repository's own `bench/`, including gitignored ones."""
    bench = ROOT / "bench"
    if not bench.exists():
        return set()
    return {str(path.relative_to(bench)) for path in bench.rglob("*")}


# Snapshot before any test runs, as `test_ledger_writer.py` does. Comparing
# against this proves the suite wrote nothing while still passing on a branch
# with uncommitted work of the contributor's own.
_BENCH_AT_IMPORT = _bench_entries()


def test_ablation_table_arithmetic_is_exact(tmp_path: Path) -> None:
    """Two cells whose means and rates can be checked by eye."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            # Arm 2, diverged, occurrence 1: one wrong fire that still succeeds,
            # one honest failure. Tokens 10 and 20 -> mean 15.
            _record(seed=1, fired_variant="rebase", tokens_in=10, llm_calls=2, wall_clock_s=1.0),
            _record(
                seed=2,
                fired_variant=None,
                ground_truth_ok=False,
                outcome=EpisodeOutcome.FAIL,
                tokens_in=20,
                llm_calls=4,
                wall_clock_s=2.0,
            ),
            # Arm 3, same cell: one invalid episode carrying a huge cost that must
            # not reach any mean, and one clean success (5+5 tokens).
            _record(
                arm=Arm.PRECONDITION,
                seed=3,
                outcome=EpisodeOutcome.INVALID,
                correct_variant=None,
                ground_truth_ok=None,
                tokens_in=999,
                llm_calls=99,
                wall_clock_s=99.0,
            ),
            _record(
                arm=Arm.PRECONDITION,
                seed=4,
                fired_variant="merge",
                tokens_in=5,
                tokens_out=5,
                llm_calls=1,
                wall_clock_s=0.5,
            ),
        ],
    )

    rows = ablation_table(ledger)
    assert [row.arm for row in rows] == [Arm.PRECONDITION, Arm.SEMANTIC]

    precondition, semantic = rows

    # Arm 3: the invalid row is in `episodes` but not in the metrics.
    assert precondition.episodes == 2
    assert precondition.graded_episodes == 1
    assert precondition.invalid == Rate(numerator=1, denominator=2)
    assert precondition.invalid.value == pytest.approx(0.5)
    assert precondition.success == Rate(numerator=1, denominator=1)
    assert precondition.mismatch == Rate(numerator=0, denominator=1)
    assert precondition.mean_tokens == Mean(n=1, value=10.0)
    assert precondition.mean_llm_calls == Mean(n=1, value=1.0)
    assert precondition.mean_wall_clock_s == Mean(n=1, value=0.5)

    # Arm 2: a wrong fire is a mismatch and also a success -- both count it.
    assert semantic.episodes == 2
    assert semantic.graded_episodes == 2
    assert semantic.invalid == Rate(numerator=0, denominator=2)
    assert semantic.success == Rate(numerator=1, denominator=2)
    assert semantic.mismatch == Rate(numerator=1, denominator=2)
    assert semantic.mean_tokens == Mean(n=2, value=15.0)
    assert semantic.mean_llm_calls == Mean(n=2, value=3.0)
    assert semantic.mean_wall_clock_s == Mean(n=2, value=1.5)


def test_every_rate_carries_its_denominator(tmp_path: Path) -> None:
    ledger = _write(tmp_path / "ledger.jsonl", [_record(seed=1), _record(seed=2)])
    (row,) = ablation_table(ledger)

    # The denominator of every metric is the graded count, and it is present.
    for rate in (row.success, row.mismatch):
        assert rate.denominator == row.graded_episodes == 2
        assert rate.numerator <= rate.denominator
    # The invalid rate's denominator is every episode in the cell, invalid included.
    assert row.invalid.denominator == row.episodes == 2
    # Means carry the count they were averaged over.
    for mean in (row.mean_tokens, row.mean_llm_calls, row.mean_wall_clock_s):
        assert mean.n == row.graded_episodes


def test_a_rate_over_an_empty_denominator_is_not_zero(tmp_path: Path) -> None:
    """0/0 is undefined, not a rate of zero -- a zero would read as a finding."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(
                seed=1,
                outcome=EpisodeOutcome.INVALID,
                correct_variant=None,
                ground_truth_ok=None,
            )
        ],
    )
    (row,) = ablation_table(ledger)
    assert row.graded_episodes == 0
    assert row.success.value is None
    assert row.mismatch.value is None
    assert row.mean_tokens == Mean(n=0, value=None)


def test_invalid_is_excluded_from_metrics_and_reported_separately(tmp_path: Path) -> None:
    """Both halves: excluding without reporting hides it from the reader, and
    reporting without excluding poisons the means with an episode that never ran."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1, tokens_in=10),
            _record(
                seed=2,
                outcome=EpisodeOutcome.INVALID,
                correct_variant=None,
                ground_truth_ok=None,
                tokens_in=1000,
            ),
        ],
    )
    (row,) = ablation_table(ledger)

    # Excluded from the metric denominators: the mean is 10, not 505.
    assert row.mean_tokens == Mean(n=1, value=10.0)
    assert row.success.denominator == 1
    assert row.mismatch.denominator == 1
    # Reported separately: 1 of 2 episodes could not run.
    assert row.invalid == Rate(numerator=1, denominator=2)
    assert row.invalid.value == pytest.approx(0.5)


def test_mismatch_and_success_come_from_derived_verdicts_not_one_stored_field(
    tmp_path: Path,
) -> None:
    """The quadrant the ledger was reshaped for: a wrong fire in a successful episode.

    `fired_variant != correct_variant` with `ground_truth_ok is True`: the mismatch
    rate counts it and the success rate counts it. A report that treated the two as
    exclusive would drop one of them from its own denominator.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(
                seed=1,
                fired_variant="rebase",
                correct_variant="merge",
                ground_truth_ok=True,
                outcome=EpisodeOutcome.SUCCESS,
            )
        ],
    )
    record = EpisodeRecord.model_validate_json(
        (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").strip()
    )
    assert record.misfired is True
    assert record.succeeded is True

    (row,) = ablation_table(ledger)
    assert row.mismatch == Rate(numerator=1, denominator=1)
    assert row.mismatch.value == 1.0
    assert row.success == Rate(numerator=1, denominator=1)
    assert row.success.value == 1.0


def test_a_wrong_fire_that_failed_is_still_a_mismatch(tmp_path: Path) -> None:
    """Mismatch is independent of the final state, so a failed wrong fire counts too."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(
                seed=1,
                fired_variant="rebase",
                correct_variant="merge",
                ground_truth_ok=False,
                outcome=EpisodeOutcome.FALLBACK,
            )
        ],
    )
    (row,) = ablation_table(ledger)
    assert row.mismatch == Rate(numerator=1, denominator=1)
    assert row.success == Rate(numerator=0, denominator=1)


# --- Wilson intervals -------------------------------------------------------


@pytest.mark.parametrize(
    ("successes", "n", "expected_low", "expected_high"),
    [
        # The middle case, checkable against any statistics table.
        (5, 10, 0.236593, 0.763407),
        # A rate of 0: the normal approximation collapses to [0, 0]; Wilson does not.
        (0, 10, 0.0, 0.277537),
        # A rate of 1, symmetric to the above.
        (10, 10, 0.722463, 1.0),
        # A single observation -- the smallest n a rate can come from.
        (1, 1, 0.206549, 1.0),
    ],
)
def test_wilson_interval_matches_known_values(
    successes: int, n: int, expected_low: float, expected_high: float
) -> None:
    """Checked by hand: 5/10 -> [0.2366, 0.7634], 0/10 -> [0.0000, 0.2775]."""
    interval = wilson_interval(successes, n)
    assert interval is not None
    assert interval.low == pytest.approx(expected_low, abs=1e-5)
    assert interval.high == pytest.approx(expected_high, abs=1e-5)
    assert 0.0 <= interval.low <= interval.high <= 1.0


def test_wilson_interval_is_none_at_n_zero() -> None:
    """There is no interval over no observations; a naive formula divides by zero."""
    assert wilson_interval(0, 0) is None


def test_wilson_interval_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        wilson_interval(-1, 10)
    with pytest.raises(ValueError):
        wilson_interval(5, 10, z=0.0)


def test_wilson_interval_is_narrower_with_more_data() -> None:
    """A rate over more episodes is not automatically a finding, but it is tighter."""
    small = wilson_interval(1, 2)
    large = wilson_interval(50, 100)
    assert small is not None and large is not None
    assert (large.high - large.low) < (small.high - small.low)


# --- The two figures --------------------------------------------------------


def test_cost_curve_groups_by_occurrence_and_arm_without_merging(tmp_path: Path) -> None:
    """Grouping by occurrence, not pooling it; and never pooling the arms."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _replay(seed=1, occurrence_index=1, tokens_in=10),
            _replay(seed=2, occurrence_index=1, tokens_in=20),
            _replay(seed=3, occurrence_index=2, tokens_in=30),
            _replay(
                arm=Arm.PRECONDITION,
                seed=4,
                occurrence_index=1,
                tokens_in=5,
            ),
        ],
    )

    points = cost_curve(ledger)
    assert [(point.arm, point.occurrence_index) for point in points] == [
        (Arm.PRECONDITION, 1),
        (Arm.SEMANTIC, 1),
        (Arm.SEMANTIC, 2),
    ]

    by_key = {(point.arm, point.occurrence_index): point for point in points}
    # Occurrence 1 and 2 are separate points, not one pooled mean.
    assert by_key[(Arm.SEMANTIC, 1)].mean_tokens == Mean(n=2, value=15.0)
    assert by_key[(Arm.SEMANTIC, 2)].mean_tokens == Mean(n=1, value=30.0)
    # The arms are separate at the same occurrence index.
    assert by_key[(Arm.SEMANTIC, 1)].mean_tokens.value != (
        by_key[(Arm.PRECONDITION, 1)].mean_tokens.value
    )
    assert by_key[(Arm.PRECONDITION, 1)].mean_tokens == Mean(n=1, value=5.0)
    for point in points:
        assert point.mean_tokens.n == point.episodes
        assert point.occurrence_role is OccurrenceRole.REPLAY


def test_cost_curve_is_computed_over_replay_occurrences_only(tmp_path: Path) -> None:
    """A variant is the learning pass, so it is not on the amortization curve.

    The two roles are on the same occurrence index and the same arm, so a curve
    that grouped by occurrence alone would average the 10-token learning pass into
    the 1-token replay and report a mean that is neither.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1, occurrence_index=1, tokens_in=10),
            _replay(seed=2, occurrence_index=1, tokens_in=1),
        ],
    )
    (point,) = cost_curve(ledger)
    assert point.episodes == 1
    assert point.mean_tokens == Mean(n=1, value=1.0)
    assert point.occurrence_role is OccurrenceRole.REPLAY


def test_cost_curve_excludes_invalid_episodes(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _replay(seed=1, tokens_in=10),
            _replay(
                seed=2,
                outcome=EpisodeOutcome.INVALID,
                correct_variant=None,
                ground_truth_ok=None,
                tokens_in=1000,
            ),
        ],
    )
    (point,) = cost_curve(ledger)
    assert point.episodes == 1
    assert point.mean_tokens == Mean(n=1, value=10.0)


def test_mismatch_comparison_matches_n_and_says_which_n(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            # Arm 2: three graded episodes, the first of which misfired.
            _record(seed=1, fired_variant="rebase"),
            _record(seed=2, fired_variant="merge"),
            _record(seed=3, fired_variant="merge"),
            # Arm 3: two graded episodes, neither misfiring.
            _record(arm=Arm.PRECONDITION, seed=1, fired_variant="merge"),
            _record(arm=Arm.PRECONDITION, seed=2, fired_variant="merge"),
        ],
    )

    comparison = mismatch_comparison(ledger)
    assert comparison.matched_n == 2
    assert comparison.semantic.available == 3
    assert comparison.precondition.available == 2

    # Each side's rate is over exactly the matched N, and says so.
    assert comparison.semantic.mismatch.denominator == comparison.matched_n == 2
    assert comparison.precondition.mismatch.denominator == comparison.matched_n == 2
    assert comparison.semantic.mismatch == Rate(numerator=1, denominator=2)
    assert comparison.precondition.mismatch == Rate(numerator=0, denominator=2)

    # Intervals are attached, and the note names N and the missing episodes.
    assert comparison.semantic.interval is not None
    assert comparison.precondition.interval is not None
    assert "Matched N=2" in comparison.note
    assert "3 graded variant episode(s)" in comparison.note
    assert "underpowered" in comparison.note
    assert comparison.occurrence_role is OccurrenceRole.VARIANT


def test_mismatch_comparison_is_computed_over_variant_occurrences_only(
    tmp_path: Path,
) -> None:
    """A replay is one observation counted again, so it is not in the interval.

    The replay misfires and succeeds, exactly as the variant beside it does: if
    the comparison pooled them the matched N would double and the interval would
    narrow on evidence that is one episode's program firing twice.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1, occurrence_index=1, fired_variant="rebase"),
            _replay(seed=2, occurrence_index=2, fired_variant="rebase"),
            _record(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, fired_variant="merge"),
            _replay(arm=Arm.PRECONDITION, seed=2, occurrence_index=2, fired_variant="merge"),
        ],
    )
    comparison = mismatch_comparison(ledger)

    assert comparison.matched_n == 1, "one graded variant episode per arm, not two"
    assert comparison.semantic.available == 1
    assert comparison.precondition.available == 1
    assert comparison.semantic.mismatch == Rate(numerator=1, denominator=1)
    assert "2 graded row(s) in this ledger" in comparison.note
    assert "variant occurrences only" in comparison.note


def test_mismatch_comparison_is_not_presented_as_the_primary_claim(tmp_path: Path) -> None:
    """The pre-registration is primary; the demo must say it is not that claim."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_record(seed=1), _record(arm=Arm.PRECONDITION, seed=1)],
    )
    comparison = mismatch_comparison(ledger)
    assert comparison.matched_n == 1
    assert "not the pre-registered analysis" in comparison.note
    assert "matched coverage" in comparison.note
    assert "read as noise" in comparison.note


def test_mismatch_comparison_reports_no_rate_for_an_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    comparison = mismatch_comparison(ledger)
    assert comparison.matched_n == 0
    assert comparison.semantic.mismatch.value is None
    assert comparison.semantic.interval is None
    assert "no rate is reported" in comparison.note


def test_small_sample_guard_fires_without_inventing_a_number(tmp_path: Path) -> None:
    """A rate over a handful of episodes is labelled noise, not printed as a finding."""
    small = mismatch_comparison(
        _write(
            tmp_path / "small.jsonl",
            [_record(seed=1), _record(arm=Arm.PRECONDITION, seed=1)],
        )
    )
    assert small.matched_n < SMALL_SAMPLE_N
    assert "small-sample guard" in small.note
    assert "read as noise" in small.note


# --- write_report -----------------------------------------------------------


def test_write_report_emits_tables_and_figures_into_dest(tmp_path: Path) -> None:
    ledger = _write(tmp_path / "ledger.jsonl", [_record(seed=1), _record(seed=2)])
    dest = tmp_path / "out"

    returned = write_report(ledger, dest)
    assert returned == dest

    for name in (
        "ablation_table.csv",
        "cost_curve.csv",
        "mismatch_comparison.csv",
        "cost_curve.png",
        "mismatch_comparison.png",
        "report.txt",
    ):
        assert (dest / name).exists(), f"{name} was not written"

    table_csv = (dest / "ablation_table.csv").read_text(encoding="utf-8")
    header = table_csv.splitlines()[0]
    # Every rate column is immediately followed by its denominator column.
    assert "success_numerator,success_denominator,success_rate" in header
    assert "mismatch_numerator,mismatch_denominator,mismatch_rate" in header
    assert "invalid_numerator,invalid_denominator,invalid_rate" in header

    # Both figures' CSVs say which occurrences they cover, so the numbers cannot
    # be read as a curve or an interval over every row.
    assert "occurrence_role" in (dest / "cost_curve.csv").read_text(encoding="utf-8")
    assert "occurrence_role" in (dest / "mismatch_comparison.csv").read_text(encoding="utf-8")

    report = (dest / "report.txt").read_text(encoding="utf-8")
    assert "NOT the pre-registered primary analysis" in report
    assert "Invalid episodes" in report
    assert "matplotlib" in report
    assert "Occurrences by role" in report
    assert "Cost curve (secondary; replay occurrences only" in report
    assert "variant occurrences only" in report


def test_write_report_flags_a_suspect_invalid_rate(tmp_path: Path) -> None:
    """Spec §7 item 9: above 10% invalid, the run is re-run rather than analysed."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1),
            _record(
                seed=2,
                outcome=EpisodeOutcome.INVALID,
                correct_variant=None,
                ground_truth_ok=None,
            ),
        ],
    )
    dest = write_report(ledger, tmp_path / "out")
    report = (dest / "report.txt").read_text(encoding="utf-8")
    assert "ABOVE 10%" in report
    assert "re-run, not analysed" in report


def test_the_report_does_not_dirty_the_repository(tmp_path: Path) -> None:
    """The suite writes only into tmp_path -- never the repository's own `bench/`."""
    write_report(
        _write(tmp_path / "ledger.jsonl", [_record(seed=1)]),
        tmp_path / "out",
    )
    assert git_status_porcelain() == GIT_STATUS_AT_IMPORT
    assert _bench_entries() == _BENCH_AT_IMPORT


# --- cumulative amortized cost and the break-even (issue #8) ------------------


def test_the_curve_accumulates_over_occurrences(tmp_path: Path) -> None:
    """Each point carries the running amortized cost, not just its own mean.

    A per-occurrence mean is a snapshot: it says what one occurrence cost, not
    whether the arm has yet paid back its compile. The accumulation is the quantity
    Claim 1 is about, and `n` grows with it so a reader can see what it averaged.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, tokens_in=100),
            _replay(arm=Arm.PRECONDITION, seed=2, occurrence_index=2, tokens_in=300),
        ],
    )

    first, second = cost_curve(ledger)
    assert first.mean_tokens == Mean(n=1, value=100.0)
    assert first.cumulative_tokens == Mean(n=1, value=100.0)
    assert second.mean_tokens == Mean(n=1, value=300.0)
    # Not 300: occurrence 1 is still in the accumulation.
    assert second.cumulative_tokens == Mean(n=2, value=200.0)
    assert second.cumulative_tokens.value > first.cumulative_tokens.value


def test_an_arm_that_gets_cheaper_reports_where_it_crosses(tmp_path: Path) -> None:
    """The break-even, which the per-occurrence mean could not exhibit.

    Arm 1's prompt grows with the transcript, so it gets dearer per occurrence,
    while the compiled arm pays for compiling once and then replays. Their
    per-occurrence means never cross here -- 500 against 100 at occurrence 1, then
    1 against 200 at occurrence 2 -- which is why the accumulation is what the
    figure plots.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _replay(arm=Arm.REACT, seed=1, occurrence_index=1, tokens_in=100),
            _replay(arm=Arm.REACT, seed=2, occurrence_index=2, tokens_in=200),
            _replay(arm=Arm.REACT, seed=3, occurrence_index=3, tokens_in=300),
            _replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, tokens_in=500),
            _replay(arm=Arm.PRECONDITION, seed=2, occurrence_index=2, tokens_in=1),
            _replay(arm=Arm.PRECONDITION, seed=3, occurrence_index=3, tokens_in=1),
        ],
    )
    points = cost_curve(ledger)

    (finding,) = break_even(points)

    assert finding.arm is Arm.PRECONDITION
    assert finding.baseline is Arm.REACT
    assert finding.occurrence_index == 3, finding.detail
    # The two readings disagree, which is why the figure had to change: the
    # per-occurrence means cross at occurrence 2, while the amortized cost -- the
    # quantity Claim 1 is about -- crosses at 3, because the compile has to be
    # digested first. Reporting the means would have claimed the earlier crossover.
    by_key = {(p.arm, p.occurrence_index): p for p in points}
    per_occurrence = [
        index
        for index in (1, 2, 3)
        if by_key[(Arm.PRECONDITION, index)].mean_tokens.value
        <= by_key[(Arm.REACT, index)].mean_tokens.value
    ]
    assert per_occurrence == [2, 3]


def test_break_even_says_which_failure_it_is(tmp_path: Path) -> None:
    """Two ways to have no crossing, and they must not read as each other.

    "The arms never share an occurrence index" is a run that cannot be compared;
    "it never crossed" is a comparison that came out against the arm. Collapsing
    them into one None would let an absent comparison look like a finding.
    """
    no_overlap = _write(
        tmp_path / "no-overlap.jsonl",
        [
            _replay(arm=Arm.REACT, seed=1, occurrence_index=1, tokens_in=10),
            _replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=2, tokens_in=1),
        ],
    )
    (finding,) = break_even(cost_curve(no_overlap))
    assert finding.occurrence_index is None
    assert "share no occurrence index" in finding.detail

    never = _write(
        tmp_path / "never.jsonl",
        [
            _replay(arm=Arm.REACT, seed=1, occurrence_index=1, tokens_in=10),
            _replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, tokens_in=100),
            _replay(arm=Arm.PRECONDITION, seed=2, occurrence_index=2, tokens_in=100),
        ],
    )
    (finding,) = break_even(cost_curve(never))
    assert finding.occurrence_index is None
    assert "never reached" in finding.detail


def test_break_even_says_when_the_baseline_arm_is_absent(tmp_path: Path) -> None:
    """A missing baseline is its own finding, not "no shared index".

    The distinction matters: with no arm 1 in the ledger, no occurrence index could
    ever be shared, so reporting the shared-index case would point a reader at the
    seeds rather than at the missing arm.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, tokens_in=10)],
    )

    (finding,) = break_even(cost_curve(ledger))
    assert finding.occurrence_index is None
    assert "react has no replay occurrence" in finding.detail


def test_break_even_is_empty_when_only_the_baseline_has_occurrences(tmp_path: Path) -> None:
    """Nothing to cross against, and no arm to report a crossing for."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_replay(arm=Arm.REACT, seed=1, occurrence_index=1, tokens_in=10)],
    )

    assert break_even(cost_curve(ledger)) == []


def test_the_report_states_the_break_even_in_words(tmp_path: Path) -> None:
    """A reader of report.txt alone must not have to eyeball the figure."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _replay(arm=Arm.REACT, seed=1, occurrence_index=1, tokens_in=100),
            _replay(arm=Arm.REACT, seed=2, occurrence_index=2, tokens_in=200),
            # Arm 1 must have occurrence 3 as well, or the comparison stops at the
            # last index the two arms share and there is no crossing to report.
            _replay(arm=Arm.REACT, seed=3, occurrence_index=3, tokens_in=300),
            _replay(arm=Arm.PRECONDITION, seed=1, occurrence_index=1, tokens_in=500),
            _replay(arm=Arm.PRECONDITION, seed=2, occurrence_index=2, tokens_in=1),
            _replay(arm=Arm.PRECONDITION, seed=3, occurrence_index=3, tokens_in=1),
        ],
    )

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "break-even: precondition's amortized cost first reached react's" in report
    assert "cumulative tokens/episode" in report


# --- spec-gaming is derived from a fact (issue #9, item 4) -------------------


def test_spec_gaming_is_counted_from_the_recorded_fact(tmp_path: Path) -> None:
    """A destructive resolution is its own column, not just a failure.

    Without this, a row that reached the expected state by destroying recorded state
    carries `ground_truth_ok=False` and is indistinguishable from one that simply did
    not repair the fault -- the finding would be invisible in exactly the table that
    is meant to report it.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            # Reached the expected state, but destroyed recorded state on the way.
            _record(seed=1, ground_truth_ok=False, refs_intact=False),
            # Reached it non-destructively.
            _record(seed=2),
            # Did not reach it at all: a plain failure, not gaming.
            _record(seed=3, ground_truth_ok=False),
        ],
    )

    (row,) = ablation_table(ledger)

    assert row.spec_gaming == Rate(numerator=1, denominator=3)
    # Gaming is a *subset* of non-success, not an orthogonal column: a resolution
    # that destroyed recorded state did not reach the expected state either, because
    # `ground_truth_ok` is the conjunction. What the column adds is the reason --
    # one of the two failures here lost its recorded refs, the other did not.
    assert row.success == Rate(numerator=1, denominator=3)


def test_a_row_whose_check_did_not_run_is_not_spec_gaming(tmp_path: Path) -> None:
    """`None` is "not checked", and counting it would flag every older row.

    The check is only consulted when the fault's own clause passes, so a row that
    failed the fault check carries `None`; so does any row written before the field
    existed. Falsy-but-not-False would sweep both into the numerator.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1, ground_truth_ok=False, refs_intact=None),
            _record(seed=2, ground_truth_ok=False, refs_intact=False),
        ],
    )

    (row,) = ablation_table(ledger)

    assert row.spec_gaming == Rate(numerator=1, denominator=2)


def test_the_report_states_the_spec_gaming_count(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(seed=1, ground_truth_ok=False, refs_intact=False),
            _record(seed=2),
        ],
    )

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "Spec-gaming" in report
    assert "tasks/invariants.py" in report
    csv = (tmp_path / "out" / "ablation_table.csv").read_text(encoding="utf-8")
    assert "spec_gaming_numerator" in csv


def test_a_run_with_no_spec_gaming_says_zero_rather_than_nothing(tmp_path: Path) -> None:
    """An absent line would leave a reader unsure whether it was checked."""
    ledger = _write(tmp_path / "ledger.jsonl", [_record(seed=1)])

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "Spec-gaming" in report
    assert "0/1" in report


# --- the triple and the Pareto frontier (issue #8, item 6) -------------------


def test_cost_per_success_is_the_arms_cost_over_its_successes(tmp_path: Path) -> None:
    """Not the mean cost of a successful episode, which is a different number.

    One success costing 100 and one failure costing 300: the arm spent 400 tokens to
    buy one success, so cost per success is 400. Averaging the successful episodes
    alone would report 100 and make an arm that fails half the time look cheapest.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1, tokens_in=100, ground_truth_ok=True),
            _record(arm=Arm.REACT, seed=2, tokens_in=300, ground_truth_ok=False),
        ],
    )

    (triple,) = arm_triples(ledger)

    assert triple.graded_episodes == 2
    assert triple.success == Rate(numerator=1, denominator=2)
    assert triple.tokens_per_episode == Mean(n=2, value=200.0)
    assert triple.tokens_per_success == Mean(n=1, value=400.0)


def test_an_arm_with_no_success_has_no_cost_per_success(tmp_path: Path) -> None:
    """0/0 has no value, and 0.0 would read as free rather than as unmeasured."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_record(arm=Arm.REACT, seed=1, tokens_in=100, ground_truth_ok=False)],
    )

    (triple,) = arm_triples(ledger)

    assert triple.tokens_per_success == Mean(n=0, value=None)
    assert triple.success == Rate(numerator=0, denominator=1)


def test_failed_episodes_stay_in_the_episode_denominator(tmp_path: Path) -> None:
    """§7 item 7: dropping them would make amortization look better than it is."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1, tokens_in=50, ground_truth_ok=True),
            _record(arm=Arm.REACT, seed=2, tokens_in=150, ground_truth_ok=False),
        ],
    )

    (triple,) = arm_triples(ledger)

    assert triple.tokens_per_episode == Mean(n=2, value=100.0)


def test_the_frontier_needs_all_three_to_be_no_worse(tmp_path: Path) -> None:
    """Dominance is on the triple, so one axis being better is not enough.

    `react` is cheaper per episode and per success and succeeds at least as often, so
    it dominates `precondition`. `semantic` never succeeds, so it has no cost per
    success to be ranked on and is reported unranked rather than as best or worst.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1, tokens_in=10, ground_truth_ok=True),
            _record(arm=Arm.REACT, seed=2, tokens_in=10, ground_truth_ok=True),
            _record(arm=Arm.PRECONDITION, seed=1, tokens_in=30, ground_truth_ok=True),
            _record(arm=Arm.PRECONDITION, seed=2, tokens_in=30, ground_truth_ok=False),
            _record(arm=Arm.SEMANTIC, seed=1, tokens_in=20, ground_truth_ok=False),
        ],
    )
    triples = arm_triples(ledger)

    pareto = pareto_frontier(triples)

    assert pareto.frontier == [Arm.REACT]
    assert [(d.arm, d.dominated_by) for d in pareto.dominated] == [(Arm.PRECONDITION, [Arm.REACT])]
    assert pareto.unranked == [Arm.SEMANTIC]


def test_a_trade_off_leaves_both_arms_on_the_frontier(tmp_path: Path) -> None:
    """The case the triple exists for: cheaper but less successful is not dominated."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1, tokens_in=10, ground_truth_ok=True),
            _record(arm=Arm.REACT, seed=2, tokens_in=10, ground_truth_ok=True),
            _record(arm=Arm.PRECONDITION, seed=1, tokens_in=1, ground_truth_ok=True),
            _record(arm=Arm.PRECONDITION, seed=2, tokens_in=1, ground_truth_ok=False),
        ],
    )

    pareto = pareto_frontier(arm_triples(ledger))

    assert sorted(a.value for a in pareto.frontier) == ["precondition", "react"]
    assert pareto.dominated == []


def test_the_report_states_the_triple_and_emits_the_pareto(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1, tokens_in=10, ground_truth_ok=True),
            _record(arm=Arm.PRECONDITION, seed=1, tokens_in=30, ground_truth_ok=True),
        ],
    )

    dest = write_report(ledger, tmp_path / "out")
    report = (dest / "report.txt").read_text(encoding="utf-8")

    assert "Arm triples" in report
    assert "tokens/success" in report
    assert "Pareto over the three" in report
    assert "on the frontier" in report
    csv = (dest / "arm_triples.csv").read_text(encoding="utf-8")
    assert "tokens_per_success" in csv and "on_frontier" in csv
    assert (dest / "pareto.png").exists()


def test_the_report_says_when_nothing_is_rankable(tmp_path: Path) -> None:
    """No success anywhere: the frontier is empty and the text must not claim one."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_record(arm=Arm.REACT, seed=1, tokens_in=10, ground_truth_ok=False)],
    )

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "on the frontier: none" in report
    assert "unranked" in report


# --- the pre-registered equivalence test (issue #8, item 8) ------------------


def test_tost_declares_equivalence_when_the_interval_fits_the_margin() -> None:
    """Two large, identical samples: the interval is inside the margin."""
    verdict = tost_equivalence(
        Rate(numerator=500, denominator=1000), Rate(numerator=505, denominator=1000)
    )

    assert verdict is not None
    assert verdict.equivalent is True
    assert verdict.margin == EQUIVALENCE_MARGIN
    assert verdict.interval.low > -EQUIVALENCE_MARGIN
    assert verdict.interval.high < EQUIVALENCE_MARGIN
    assert "equivalent at this margin" in verdict.reason


def test_tost_refuses_equivalence_when_the_interval_leaves_the_margin() -> None:
    """A real difference: the interval lies wholly outside, which is not underpower."""
    verdict = tost_equivalence(
        Rate(numerator=900, denominator=1000), Rate(numerator=100, denominator=1000)
    )

    assert verdict is not None
    assert verdict.equivalent is False
    assert "not merely underpowered" in verdict.reason


def test_tost_distinguishes_underpowered_from_different() -> None:
    """The distinction the item turns on, and the one a bare "not equivalent" erases.

    Two episodes each: the rates are close, but no interval this wide can fit inside
    the margin, so the run cannot show equivalence. Saying "not equivalent" here would
    read as evidence the arms differ, which two episodes cannot be.
    """
    verdict = tost_equivalence(Rate(numerator=1, denominator=2), Rate(numerator=1, denominator=2))

    assert verdict is not None
    assert verdict.equivalent is False
    assert "underpowered to show equivalence" in verdict.reason
    assert "not the same as showing the arms differ" in verdict.reason


def test_tost_needs_two_rates() -> None:
    """0/0 is not a rate, so there is nothing to compare."""
    assert (
        tost_equivalence(Rate(numerator=0, denominator=0), Rate(numerator=1, denominator=2)) is None
    )


def test_the_wording_follows_the_test_not_the_author() -> None:
    """Spec §7 item 10: "equal" only where the test passes, else "comparable"."""
    equal, equal_verdict = success_rate_wording(
        Rate(numerator=500, denominator=1000), Rate(numerator=502, denominator=1000)
    )
    comparable, comparable_verdict = success_rate_wording(
        Rate(numerator=1, denominator=2), Rate(numerator=1, denominator=2)
    )

    assert equal == "equal success rate"
    assert equal_verdict is not None and equal_verdict.equivalent is True
    assert comparable == "comparable success rate"
    assert comparable_verdict is not None and comparable_verdict.equivalent is False


def test_the_report_states_the_equivalence_verdict(tmp_path: Path) -> None:
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_record(arm=Arm.SEMANTIC, seed=1), _record(arm=Arm.PRECONDITION, seed=1)],
    )

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "Success-rate equivalence" in report
    assert "margin +/-10%" in report
    # Two episodes cannot show equivalence, so the report must not say "equal".
    assert '"comparable success rate"' in report
    assert "underpowered" in report


def test_the_report_registers_the_margin_it_used(tmp_path: Path) -> None:
    """An equivalence verdict without its margin and alpha says nothing."""
    ledger = _write(tmp_path / "ledger.jsonl", [_record(arm=Arm.SEMANTIC, seed=1)])
    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")
    assert "alpha 0.05" in report


# --- the raw prompt prefix (issue #8, item 5) --------------------------------


def test_the_prefix_lengths_are_the_prompts_actually_sent() -> None:
    """Measured from the constants, not restated as a number that can drift."""
    from precondition_library.agents import compile as compile_agent
    from precondition_library.agents import react

    prefixes = {prefix.phase: prefix for prefix in prompt_prefix_lengths()}

    assert prefixes["learn (ReAct)"].chars == len(react.SYSTEM_PROMPT)
    assert prefixes["compile"].chars == len(compile_agent._system_prompt(None))
    # Raw characters, so a positive length that is not a token count.
    assert all(prefix.chars > 0 for prefix in prefixes.values())


def test_the_compile_prefix_grows_when_variant_ids_are_named() -> None:
    """The one of the two that is not a fixed constant, said in the report as such."""
    from precondition_library.agents import compile as compile_agent

    with_ids = len(compile_agent._system_prompt(["discard", "merge"]))

    assert with_ids > len(compile_agent._system_prompt(None))


def test_the_report_reports_the_prefix_once_not_per_arm(tmp_path: Path) -> None:
    """A per-arm column would print one number three times and imply a difference.

    All three arms send the same two prompts, so the report states them once and says
    why; the arm-level difference is transcript growth, which the input tokens carry.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(arm=Arm.REACT, seed=1),
            _record(arm=Arm.SEMANTIC, seed=1),
            _record(arm=Arm.PRECONDITION, seed=1),
        ],
    )

    report = (write_report(ledger, tmp_path / "out") / "report.txt").read_text(encoding="utf-8")

    assert "Prompt prefixes the run sends" in report
    assert "shared by every arm" in report
    assert report.count("learn (ReAct):") == 1


# --- input is metered in three components (issue #8, items 1-2) --------------


def test_the_table_reports_uncached_and_cache_read_separately(tmp_path: Path) -> None:
    """One summed input number cannot be priced, so the components are columns.

    A cache hit is billed at a fraction of a miss, so a reader given only the total has
    to price cached tokens at the uncached rate -- which overstates exactly the arm that
    caches most, and arm 1 is the one whose prompt grows.
    """
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [_record(seed=1, tokens_in=1000, uncached_tokens_in=128, cached_tokens_in=872)],
    )

    (row,) = ablation_table(ledger)

    assert row.mean_uncached_tokens_in == Mean(n=1, value=128.0)
    assert row.mean_cached_tokens_in == Mean(n=1, value=872.0)
    assert row.mean_cache_write_tokens_in == Mean(n=1, value=0.0)


def test_the_components_survive_the_ledger_round_trip(tmp_path: Path) -> None:
    """Written by the runner, read back by the report: the fields must not be dropped."""
    ledger = _write(
        tmp_path / "ledger.jsonl",
        [
            _record(
                seed=1,
                tokens_in=1000,
                uncached_tokens_in=200,
                cached_tokens_in=750,
                cache_write_tokens_in=50,
            )
        ],
    )

    (row,) = ablation_table(ledger)

    assert row.mean_uncached_tokens_in.value == 200.0
    assert row.mean_cached_tokens_in.value == 750.0
    assert row.mean_cache_write_tokens_in.value == 50.0


def test_the_report_warns_that_the_total_is_not_a_billing_basis(tmp_path: Path) -> None:
    """The mispricing hazard stated where the cost figure is, not only in the schema."""
    ledger = _write(tmp_path / "ledger.jsonl", [_record(seed=1, tokens_in=100)])
    dest = write_report(ledger, tmp_path / "out")

    report = (dest / "report.txt").read_text(encoding="utf-8")

    assert "NOT a billing basis" in report
    csv = (dest / "ablation_table.csv").read_text(encoding="utf-8")
    assert "mean_uncached_tokens_in" in csv and "mean_cache_write_tokens_in" in csv
