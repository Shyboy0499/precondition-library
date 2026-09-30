"""The mismatch-vs-coverage machinery (issue #5, ADR-0008), on synthetic and gold outcomes.

The arithmetic is pinned on hand-built outcomes, where every number can be checked by
counting. One test runs the whole path on the committed gold programs, because that is
where the degeneracy guard has to fire: hand-written arm 3 agrees with the labelling
rules, so the comparison it would produce is vacuous, and the harness must say so.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.bench.coverage import (
    PairOutcome,
    arm2_outcomes,
    arm3_outcomes,
    detectable_difference,
    matched_comparison,
    operating_point,
    sweep,
    vacuous_reason,
)
from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.similarity_probe import program_text_candidates
from precondition_library.bench.splits import TUNE_SEEDS
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.state_grid import STATE_GRID


def _outcome(
    correct: str | None, fired: str | None, score: float | None = None, *, informed: bool = True
) -> PairOutcome:
    return PairOutcome(correct_variant=correct, fired_variant=fired, score=score, informed=informed)


# Arm 2 on five pairs, one of them negative. Scores are distinct so every threshold is
# a different operating point.
ARM2 = [
    _outcome("merge", "merge", 0.9),
    _outcome("rebase", "merge", 0.7),
    _outcome("discard", "discard", 0.5),
    _outcome(None, "merge", 0.3),
    _outcome("rebase", "rebase", 0.1),
]


def test_mismatch_is_per_fire_and_a_fire_on_a_negative_is_wrong() -> None:
    """At 0.3 four pairs fire: one wrong variant and one fire on a negative, so 2 of 4."""
    point = operating_point(ARM2, 0.3)
    assert (point.coverage.numerator, point.coverage.denominator) == (4, 5)
    assert (point.mismatch.numerator, point.mismatch.denominator) == (2, 4)
    assert point.mismatch_interval is not None


def test_the_threshold_is_an_inclusive_floor() -> None:
    """`Library.match_semantic` fires at `score >= threshold`, so the sweep must too."""
    assert operating_point(ARM2, 0.5).coverage.numerator == 3
    assert operating_point(ARM2, 0.50001).coverage.numerator == 2


def test_the_sweep_has_one_point_per_distinct_score_strictest_first() -> None:
    curve = sweep(ARM2)
    assert [point.threshold for point in curve] == [0.9, 0.7, 0.5, 0.3, 0.1]
    assert [point.coverage.numerator for point in curve] == [1, 2, 3, 4, 5]
    assert [point.mismatch.numerator for point in curve] == [0, 1, 1, 2, 2]


def test_nothing_fired_has_no_mismatch_rather_than_zero() -> None:
    point = operating_point(ARM2, 1.0)
    assert point.coverage.numerator == 0
    assert point.mismatch.value is None
    assert point.mismatch_interval is None


def test_a_dispatcher_without_a_score_is_a_point_not_a_curve() -> None:
    """Arm 3 has no score, so sweeping it is refused rather than returning one point."""
    arm3 = [_outcome("merge", "merge"), _outcome(None, None)]
    with pytest.raises(ValueError, match="no score"):
        sweep(arm3)
    point = operating_point(arm3)
    assert point.threshold is None
    assert (point.coverage.numerator, point.mismatch.numerator) == (1, 0)


def test_the_regimes_are_never_pooled() -> None:
    mixed = [_outcome("merge", "merge", 0.5), _outcome("merge", "merge", 0.5, informed=False)]
    with pytest.raises(ValueError, match="never pooled"):
        operating_point(mixed)
    with pytest.raises(ValueError, match="never pooled"):
        sweep(mixed)
    with pytest.raises(ValueError, match="never pooled"):
        vacuous_reason(mixed)


def test_matched_coverage_is_the_nearest_point_and_a_tie_goes_lower() -> None:
    """Arm 3 at 3/5 coverage; arm 2's 2/5 and 4/5 are equally near, so 2/5 is chosen.

    The lower coverage usually has the lower arm-2 mismatch, so the tie-break cannot be
    the thing that makes arm 3 look better.
    """
    arm3 = operating_point(
        [_outcome("a", "a"), _outcome("b", "b"), _outcome("c", "a"), _outcome(None, None)]
        + [_outcome("d", None)]
    )
    assert (arm3.coverage.numerator, arm3.coverage.denominator) == (3, 5)
    curve = [point for point in sweep(ARM2) if point.coverage.numerator in (2, 4)]
    matched = matched_comparison(curve, arm3)
    assert matched.arm2.coverage.numerator == 2
    assert matched.coverage_gap == pytest.approx(-0.2)
    # arm 2 at 2/5 has mismatch 1/2; arm 3 has 1/3.
    assert matched.mismatch_difference == pytest.approx(1 / 2 - 1 / 3)


def test_matching_refuses_what_cannot_be_matched() -> None:
    with pytest.raises(ValueError, match="no pairs"):
        matched_comparison(sweep(ARM2), operating_point([]))
    with pytest.raises(ValueError, match="empty"):
        matched_comparison([], operating_point(ARM2[:1], 0.0))


def test_an_arm_that_cannot_lose_is_reported_as_vacuous() -> None:
    oracle = [_outcome("merge", "merge"), _outcome(None, None)]
    assert "labelling rule" in (vacuous_reason(oracle) or "")
    fallible = [*oracle, _outcome("rebase", "merge")]
    assert vacuous_reason(fallible) is None


def test_the_detectable_difference_shrinks_with_more_fires() -> None:
    """At a 50% base rate, 100 fires per arm detect about 19.8 points at the defaults."""
    at_100 = detectable_difference(100, 100, base_rate=0.5)
    at_400 = detectable_difference(400, 400, base_rate=0.5)
    assert at_100 == pytest.approx(0.198, abs=5e-4)
    assert at_400 is not None and at_100 is not None and at_400 < at_100
    assert detectable_difference(0, 100, base_rate=0.5) is None
    with pytest.raises(ValueError):
        detectable_difference(10, 10, base_rate=0.5, alpha=0.0)


def test_hand_written_arm3_is_the_answer_key_on_the_tune_pairs() -> None:
    """End to end on gold: arm 2 traces a real curve, and arm 3 trips the guard.

    Arm 3 is played by the intents' own decision rule -- what the hand-written gold
    programs were checked to agree with -- so it decides every pair correctly, in both
    regimes, and `vacuous_reason` must say the comparison is not yet an experiment.
    """
    for informed in (True, False):
        arm2: list[PairOutcome] = []
        arm3: list[PairOutcome] = []
        for intent in ambiguous_intents():
            pairs = [
                pair
                for pair in labelled_pairs(
                    intent, list(STATE_GRID[intent.name].values()), list(TUNE_SEEDS)
                )
                if pair.informed == informed
            ]
            candidates = program_text_candidates(gold_programs(intent.name))
            arm2 += arm2_outcomes(pairs, candidates, lexical_similarity)
            arm3 += arm3_outcomes(pairs, lambda pair: pair.correct_variant)
        curve = sweep(arm2)
        assert len(curve) > 1, "arm 2's scores should give more than one operating point"
        assert curve[-1].coverage.numerator == len(arm2), "the loosest point fires on every pair"
        assert vacuous_reason(arm3) is not None
        matched = matched_comparison(curve, operating_point(arm3))
        assert matched.arm3.mismatch.numerator == 0
