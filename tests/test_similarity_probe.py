"""The discrimination probe measures a scorer, and it can tell scorers apart (#104).

A measurement nobody has seen separate a known-good from a known-bad scorer is not a
measurement. These tests pin the two ends: a scorer that cannot discriminate scores 0.5, and one
that ranks the same scores backwards scores exactly the complement. Between them they say the AUC
is computed from what the scorer returned rather than from the pairs.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.similarity_probe import (
    PROBE_SEEDS,
    compare_scorers,
    discrimination_auc,
    discrimination_scores,
)
from precondition_library.bench.textcontrol import roc_auc
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.state_grid import STATE_GRID

INTENT = next(intent for intent in ambiguous_intents() if intent.name == "sync_fork_with_upstream")
PAIRS = labelled_pairs(INTENT, list(STATE_GRID[INTENT.name].values()), list(PROBE_SEEDS))


def test_a_scorer_that_cannot_discriminate_scores_one_half() -> None:
    """Every score equal: no ranking, so the AUC is 0.5 by definition.

    The floor matters because it is what a pointless scorer earns, and a probe that reported 0.0
    for it would be reporting an inverted ranking instead.
    """

    def constant(query: str, candidate: str) -> float:
        return 0.5

    assert discrimination_auc(PAIRS, INTENT.variants, constant) == pytest.approx(0.5)


def test_inverting_a_scorers_scores_inverts_its_auc() -> None:
    """The complement property, which is what proves the AUC reads the scores.

    If the number came from the pairs rather than from what the scorer returned, an inverted
    scorer would score the same. It cannot.
    """

    def inverted(query: str, candidate: str) -> float:
        return -lexical_similarity(query, candidate)

    forward = discrimination_auc(PAIRS, INTENT.variants, lexical_similarity)
    backward = discrimination_auc(PAIRS, INTENT.variants, inverted)

    assert forward is not None and backward is not None
    assert backward == pytest.approx(1.0 - forward)


def test_the_crossings_include_negatives() -> None:
    """No correct resolution means every resolution is wrong: the half an always-fires scorer fails.

    Asserted on the crossing itself, because a probe built only from positive pairs would report a
    high AUC for a scorer that ranks arbitrarily.
    """
    scores, positives = discrimination_scores(PAIRS, INTENT.variants, lexical_similarity)

    assert scores and len(scores) == len(positives)
    assert len(scores) == len(PAIRS) * len(INTENT.variants)
    assert any(positives) and not all(positives), "the probe needs both classes to compute an AUC"


def test_the_lexical_scorer_is_measured_not_gated() -> None:
    """The shipped scorer's own number, reported as a value in range rather than asserted.

    Gating it would make an exploratory figure into a claim; the assertion here is only that the
    probe produced a usable number for it.
    """
    auc = discrimination_auc(PAIRS, INTENT.variants, lexical_similarity)

    assert auc is not None
    assert 0.0 <= auc <= 1.0


def test_comparing_scorers_gives_each_the_same_pairs() -> None:
    """A comparison is only a comparison if the denominators match."""
    findings = compare_scorers({"lexical": lexical_similarity, "constant": lambda q, c: 0.0})

    assert [finding.scorer for finding in findings] == ["constant", "lexical"]
    assert len({finding.pairs for finding in findings}) == 1
    assert len({finding.comparisons for finding in findings}) == 1
    assert all(finding.pairs > 0 and finding.comparisons > 0 for finding in findings)


def test_a_single_class_reports_none_rather_than_zero() -> None:
    """`roc_auc` refuses one class, and `None` is not 0.0: unmeasured is not measured-zero."""
    # Built directly rather than by filtering pairs: crossing one pair with several variants
    # always produces both classes, because at most one variant can be correct for it. One pair
    # against only its own correct resolution is the single-class case.
    pair = next(candidate for candidate in PAIRS if candidate.correct_variant is not None)
    only_correct = [v for v in INTENT.variants if v.id == pair.correct_variant]

    assert discrimination_auc([pair], only_correct, lexical_similarity) is None


def test_the_probe_seeds_are_not_the_pre_registered_plan() -> None:
    """Named separately so nobody reads an exploratory figure as the eval split."""
    from precondition_library.bench.splits import EVAL_SEEDS, TUNE_SEEDS

    assert not set(PROBE_SEEDS) & set(EVAL_SEEDS)
    assert not set(PROBE_SEEDS) & set(TUNE_SEEDS)
    assert roc_auc([1.0, 0.0], [True, False]) == 1.0
