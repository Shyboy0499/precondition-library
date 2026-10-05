"""The primary metric's report: Figure 1, the comparison and the power statement (issue #5).

`bench.primary` assembles what spec §7 pre-registers -- arm 2's curve with a Wilson
interval at every operating point, arm 3's point as the coverage point, the matched
comparison, the item-3 power statement -- and puts the vacuity guard ahead of it. Run
on synthetic outcomes: the arithmetic must not wait for a compiled library.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from precondition_library.bench.coverage import PairOutcome, detectable_difference
from precondition_library.bench.primary import (
    CONSERVATIVE_BASE_RATE,
    primary_report,
    summary,
    write_primary_report,
)


def _o(correct: str | None, fired: str | None, score: float | None = None, *, informed=False):
    return PairOutcome(correct_variant=correct, fired_variant=fired, score=score, informed=informed)


# Eight pairs, two of them negatives. Arm 2 is scored and sometimes wrong; arm 3 is
# fallible too (one wrong fire), so the comparison is an experiment.
ARM2 = [
    _o("merge", "merge", 0.9),
    _o("rebase", "merge", 0.8),
    _o("discard", "discard", 0.7),
    _o("merge", "rebase", 0.6),
    _o("rebase", "rebase", 0.5),
    _o("discard", "discard", 0.4),
    _o(None, "merge", 0.3),
    _o(None, "rebase", 0.2),
]
ARM3 = [
    _o("merge", "merge"),
    _o("rebase", "rebase"),
    _o("discard", None),
    _o("merge", "merge"),
    _o("rebase", "merge"),
    _o("discard", "discard"),
    _o(None, None),
    _o(None, None),
]


def test_every_curve_point_carries_a_wilson_interval() -> None:
    report = primary_report(ARM2, ARM3)
    assert report.arm2.scored is True
    assert len(report.arm2.points) == 8, "one point per distinct score"
    assert all(point.mismatch_interval is not None for point in report.arm2.points)


def test_arm_3_is_the_coverage_point_and_the_comparison_is_matched_to_it() -> None:
    report = primary_report(ARM2, ARM3)
    assert (report.arm3.coverage.numerator, report.arm3.coverage.denominator) == (5, 8)
    assert (report.arm3.mismatch.numerator, report.arm3.mismatch.denominator) == (1, 5)
    assert report.vacuous is None, "arm 3 mis-fires once, so this is an experiment"
    assert report.matched is not None
    assert report.matched.arm2.coverage.numerator == 5, "arm 2's point at arm 3's coverage"


def test_the_power_statement_is_given_at_the_conservative_rate() -> None:
    report = primary_report(ARM2, ARM3)
    assert report.power is not None
    fires = (report.power.arm2_fires, report.power.arm3_fires)
    assert fires == (5, 5)
    assert report.power.at_conservative_rate == pytest.approx(
        detectable_difference(5, 5, base_rate=CONSERVATIVE_BASE_RATE)
    )
    assert report.power.observed_rate is not None and 0.0 < report.power.observed_rate < 1.0
    assert report.power.at_observed_rate is not None


def test_a_vacuous_comparison_is_stated_instead_of_compared() -> None:
    """Arm 3 right on every pair is the labelling rule; no comparison may be read off."""
    oracle = [_o(o.correct_variant, o.correct_variant) for o in ARM2]
    report = primary_report(ARM2, oracle)
    assert report.vacuous is not None
    text = summary(report)
    assert "NO COMPARISON" in text
    assert "at matched coverage" not in text


def test_an_arm_2_that_never_fires_has_no_comparison() -> None:
    silent = [_o(o.correct_variant, None) for o in ARM2]
    report = primary_report(silent, ARM3)
    assert report.matched is None and report.power is None
    assert "fired on no pair" in summary(report)


def test_regimes_are_never_pooled() -> None:
    mixed = [*ARM2[:-1], _o(None, "rebase", 0.2, informed=True)]
    with pytest.raises(ValueError, match="one regime"):
        primary_report(mixed, ARM3)


def test_both_arms_must_be_run_on_the_same_pairs() -> None:
    with pytest.raises(ValueError, match="one set of pairs"):
        primary_report(ARM2[:-1], ARM3)


def test_baselines_join_the_plane_as_curves_or_points() -> None:
    soft = [_o(o.correct_variant, o.correct_variant, 1.0) for o in ARM2]
    key = [_o(o.correct_variant, None) for o in ARM2]
    report = primary_report(ARM2, ARM3, baselines={"2b soft vote": soft, "2c intent key": key})
    kinds = {baseline.name: baseline.scored for baseline in report.baselines}
    assert kinds == {"2b soft vote": True, "2c intent key": False}
    with pytest.raises(ValueError, match="same pairs"):
        primary_report(ARM2, ARM3, baselines={"short": soft[:-1]})


def test_the_report_writes_figure_1_and_its_text(tmp_path: Path) -> None:
    report = primary_report(ARM2, ARM3, baselines={"2c intent key": ARM3})
    dest = write_primary_report(report, tmp_path / "primary")

    rows = list(csv.DictReader((dest / "figure1.csv").open(encoding="utf-8")))
    coverage_points = [row for row in rows if row["coverage_point"] == "True"]
    assert [row["dispatcher"] for row in coverage_points] == ["arm 3 (precondition)"]
    assert all(row["wilson_low"] != "" for row in rows if row["fires"] != "0")
    assert "power (item 3)" in (dest / "primary.txt").read_text(encoding="utf-8")
    assert (dest / "figure1.png").stat().st_size > 0


def test_an_error_bar_is_never_negative_even_from_an_interval_off_its_point() -> None:
    """A bound a rounding error on the wrong side of its point made a negative error bar,
    and the eleventh live run's Figure 1 plot crashed on it after the build."""
    from precondition_library.bench.coverage import OperatingPoint
    from precondition_library.bench.primary import _errors
    from precondition_library.bench.report import Interval, Rate

    off = OperatingPoint(
        threshold=0.5,
        coverage=Rate(numerator=6, denominator=10),
        mismatch=Rate(numerator=6, denominator=6),
        mismatch_interval=Interval(low=0.6, high=0.9999999999999999),
    )
    _, low, high = _errors([off])
    assert low[0] >= 0 and high[0] >= 0
