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

import os
import subprocess
from pathlib import Path

import pytest

from precondition_library.bench.ledger import Arm, EpisodeRecord, append
from precondition_library.bench.report import (
    SMALL_SAMPLE_N,
    Mean,
    Rate,
    ablation_table,
    cost_curve,
    mismatch_comparison,
    wilson_interval,
    write_report,
)
from precondition_library.program import EpisodeOutcome

ROOT = Path(__file__).resolve().parents[1]


def _record(**overrides) -> EpisodeRecord:
    base = {
        "arm": Arm.SEMANTIC,
        "task_id": "sync_fork_with_upstream",
        "fault_type": "diverged",
        "occurrence_index": 1,
        "seed": 1,
        "tokens_in": 0,
        "tokens_out": 0,
        "llm_calls": 0,
        "wall_clock_s": 0.0,
        "outcome": EpisodeOutcome.SUCCESS,
        "model": "test",
        "correct_variant": "merge",
        "ground_truth_ok": True,
    }
    base.update(overrides)
    return EpisodeRecord(**base)


def _write(path: Path, records: list[EpisodeRecord]) -> Path:
    for record in records:
        append(path, record)
    return path


def _git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ},
    )
    return result.stdout


def _bench_entries() -> set[str]:
    """Every path under the repository's own `bench/`, including gitignored ones."""
    bench = ROOT / "bench"
    if not bench.exists():
        return set()
    return {str(path.relative_to(bench)) for path in bench.rglob("*")}


# Snapshot before any test runs, as `test_ledger_writer.py` does. Comparing
# against this proves the suite wrote nothing while still passing on a branch
# with uncommitted work of the contributor's own.
_GIT_STATUS_AT_IMPORT = _git_status()
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
    record = EpisodeRecord.model_validate_json((tmp_path / "ledger.jsonl").read_text().strip())
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
            _record(seed=1, occurrence_index=1, tokens_in=10),
            _record(seed=2, occurrence_index=1, tokens_in=20),
            _record(seed=3, occurrence_index=2, tokens_in=30),
            _record(
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


def test_cost_curve_excludes_invalid_episodes(tmp_path: Path) -> None:
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
    assert "3 graded episode(s)" in comparison.note
    assert "underpowered" in comparison.note


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

    report = (dest / "report.txt").read_text(encoding="utf-8")
    assert "NOT the pre-registered primary analysis" in report
    assert "Invalid episodes" in report
    assert "matplotlib" in report


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
    assert _git_status() == _GIT_STATUS_AT_IMPORT
    assert _bench_entries() == _BENCH_AT_IMPORT
