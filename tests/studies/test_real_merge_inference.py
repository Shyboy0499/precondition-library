"""The real-merge study's registered tests, on outcomes whose answers are worked out by hand."""

from __future__ import annotations

import math

import pytest

from precondition_library.experiment.coverage import PairOutcome
from precondition_library.studies.real_merge_inference import (
    Clustered,
    cluster_bootstrap,
    decide,
    matched_difference,
    matched_test,
    mcnemar,
    refusal_difference,
    refusal_test,
)


def _outcome(
    fired: str | None, acceptable: tuple[str, ...], score: float | None = None
) -> PairOutcome:
    return PairOutcome(
        correct_variant=acceptable[0] if acceptable else None,
        acceptable_variants=acceptable,
        fired_variant=fired,
        score=score if fired is not None else None,
        informed=False,
    )


def _clean(repo: str, arm3: str | None, other: str | None, score: float = 0.5) -> Clustered:
    """A clean case: `merge` is right."""
    return Clustered(
        repo=repo,
        arm3=_outcome(arm3, ("merge",)),
        other=_outcome(other, ("merge",), score),
        inexpressible_conflict=False,
    )


def _conflict(repo: str, arm3: str | None, other: str | None, score: float = 0.5) -> Clustered:
    """A conflicted case nothing reproduces: only refusing is right."""
    return Clustered(
        repo=repo,
        arm3=_outcome(arm3, ()),
        other=_outcome(other, (), score),
        inexpressible_conflict=True,
    )


@pytest.mark.parametrize(
    ("b", "c", "expected"),
    [
        (0, 0, None),
        (5, 0, 2 / 32),
        (3, 3, 1.0),
        (10, 2, 2 * (1 + 12 + 66) / 4096),
        (2, 10, 2 * (1 + 12 + 66) / 4096),
    ],
)
def test_mcnemar_is_the_exact_two_sided_test(b: int, c: int, expected: float | None) -> None:
    got = mcnemar(b, c)
    assert got == expected if expected is None else math.isclose(got or -1, expected)


def test_arm_3_right_where_the_other_is_wrong_differs_by_one() -> None:
    rows = [_clean(f"r{i}", "merge", "rebase") for i in range(4)]
    assert matched_difference(rows) == 1.0
    test = matched_test(rows)
    assert test.statistic == 1.0
    assert test.discordant == (4, 0)
    assert test.p_value == 2 / 16
    assert test.interval is not None and (test.interval.low, test.interval.high) == (1.0, 1.0)


def test_no_arm_3_fire_leaves_the_difference_undefined() -> None:
    rows = [_clean("r", None, "merge")]
    assert matched_difference(rows) is None
    assert matched_test(rows).statistic is None


def test_refusal_counts_fires_on_inexpressible_conflicts_only() -> None:
    rows = [
        _conflict("r1", None, "keep_local"),
        _conflict("r2", None, "keep_local"),
        _conflict("r3", "keep_local", "keep_local"),
        _clean("r4", "merge", "merge"),
    ]
    # The control fires on all three conflicts, arm 3 on one of them.
    assert refusal_difference(rows) == pytest.approx(2 / 3)
    test = refusal_test(rows)
    assert test.discordant == (2, 0)
    assert test.p_value == 0.5


def test_the_bootstrap_resamples_repositories_and_is_reproducible() -> None:
    rows = [_clean("a", "merge", "rebase"), _clean("a", "merge", "merge")] + [
        _clean("b", "merge", "merge") for _ in range(4)
    ]
    first = cluster_bootstrap(rows, matched_difference)
    assert first == cluster_bootstrap(rows, matched_difference)
    interval, skipped = first
    assert skipped == 0
    assert interval is not None
    # Repository a alone gives 0.5, b alone 0: every resample lies between.
    assert 0.0 <= interval.low <= interval.high <= 0.5


def test_the_rules_apply_in_order() -> None:
    few = [_outcome("merge", ("merge",)) for _ in range(19)]
    tested = matched_test([_clean("r", "merge", "rebase")])
    assert decide(few, tested, tested, underpowered=False)[0].outcome.startswith("not tested")

    wrong = [_outcome("keep_local", ()) for _ in range(30)]
    decisions = decide(wrong, tested, tested, underpowered=False)
    assert [d.rule[0] for d in decisions] == ["1", "2", "3", "4"]
    assert decisions[1].outcome.startswith("falsified")

    right = [_outcome("merge", ("merge",)) for _ in range(30)]
    rows = [_clean(f"r{i}", "merge", "rebase") for i in range(10)]
    h = matched_test(rows)
    assert decide(right, h, h, underpowered=False)[2].outcome.startswith("supported")
    assert decide(right, h, h, underpowered=True)[2].outcome.startswith("underpowered")
