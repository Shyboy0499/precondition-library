"""The discrimination probe measures a scorer, and it can tell scorers apart (#104, #116).

A measurement nobody has seen separate a known-good from a known-bad scorer is not a measurement.
These tests pin the two ends: a scorer that cannot discriminate scores 0.5, and one that ranks the
same scores backwards scores exactly the complement. Between them they say the AUC is computed from
what the scorer returned rather than from the pairs.

**The tests that matter most are the real ones**, added after #116: they use the hand-written
gold programs, `library._program_text` and the shipped `lexical_similarity`, with no stand-ins, and
they assert the two candidate sources **disagree**. That disagreement is what the probe's first
version missed -- it measured each resolution's `rationale` rather than the artifact a dispatcher
scores, and reported 0.70 where the real figure is 0.48. A test asserting the sources differ would
have caught it on the day, so one exists now.

The two synthetic scorers below are controls, not stand-ins for project code: the seam is a
`Protocol` the project injects by design, and a constant is the only way to show what the floor
looks like. Everything else here runs the real thing.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.similarity_probe import (
    PROBE_SEEDS,
    compare_scorers,
    discrimination_auc,
    discrimination_scores,
    program_text_candidates,
    rationale_candidates,
    top1_accuracy,
)
from precondition_library.bench.textcontrol import roc_auc
from precondition_library.library import _program_text
from precondition_library.program import Program
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.state_grid import STATE_GRID

INTENT = next(intent for intent in ambiguous_intents() if intent.name == "sync_fork_with_upstream")
PAIRS = labelled_pairs(INTENT, list(STATE_GRID[INTENT.name].values()), list(PROBE_SEEDS))
PROGRAMS = gold_programs(INTENT.name)
ARTIFACT = program_text_candidates(PROGRAMS)
RATIONALE = rationale_candidates(INTENT)


# --- the real measurement: the artifact a dispatcher scores -------------------


def test_the_candidate_text_is_the_one_the_dispatcher_scores() -> None:
    """The candidates are `_program_text`, so the probe cannot measure a different text again.

    Called rather than re-implemented: a copy of the dispatcher's text builder here would be free to
    drift from `library._program_text`, which is exactly how the probe came to score rationales.
    """
    for program in PROGRAMS:
        assert ARTIFACT[program.variant] == _program_text(program)

    print("\ncandidate texts a dispatcher compares against:")
    for variant, text in sorted(ARTIFACT.items()):
        print(f"  {variant:8s} {text[:88]!r}")


def test_the_two_candidate_sources_disagree() -> None:
    """The regression guard for issue #116, and the test the first version lacked.

    `rationale` is the intent designer's explanation; `_program_text` is the artifact. They are
    different texts with different mutual redundancy, so they produce different numbers -- and the
    difference is not small: it is the difference between "the baseline discriminates somewhat" and
    "the baseline is at chance". A future edit that swapped one source for the other would show up
    here as a changed number rather than as a quietly wrong baseline.
    """
    artifact_auc = discrimination_auc(PAIRS, ARTIFACT, lexical_similarity)
    rationale_auc = discrimination_auc(PAIRS, RATIONALE, lexical_similarity)

    assert artifact_auc is not None and rationale_auc is not None
    print(
        f"\n  artifact (_program_text): AUC={artifact_auc:.4f}"
        f" top-1={top1_accuracy(PAIRS, ARTIFACT, lexical_similarity)}"
    )
    print(
        f"  rationale (diagnostic)  : AUC={rationale_auc:.4f}"
        f" top-1={top1_accuracy(PAIRS, RATIONALE, lexical_similarity)}"
    )

    assert rationale_auc - artifact_auc > 0.15, (
        "the two candidate sources are supposed to differ materially; if they no longer do, the "
        "texts changed and #116's finding needs re-measuring rather than this bound loosening"
    )


def test_the_artifact_baseline_is_reported_not_gated() -> None:
    """The baseline number, printed with its denominators and asserted only to be well formed.

    Deliberately not asserted against a threshold. The figure is currently *below* chance, which is
    #116's finding; pinning it here would turn a defect into an expectation and fail the moment
    somebody fixes the scorer. What is asserted is that the measurement is usable: the AUC is a
    number, and top-1 counts exactly the pairs that have a correct answer.
    """
    auc = discrimination_auc(PAIRS, ARTIFACT, lexical_similarity)
    decided, total = top1_accuracy(PAIRS, ARTIFACT, lexical_similarity)

    assert auc is not None and 0.0 <= auc <= 1.0
    assert total == sum(1 for pair in PAIRS if pair.correct_variant is not None)
    assert 0 <= decided <= total

    print(
        f"\n  shipped lexical scorer on the gold artifact: AUC={auc:.4f},"
        f" strict top-1 {decided}/{total}, across {len(PAIRS)} pairs"
        f" (chance for {len(ARTIFACT)} candidates = {1 / len(ARTIFACT):.2f})"
    )


def test_top1_counts_only_pairs_that_have_a_correct_answer() -> None:
    """The denominator: a negative pair has no right program, so it is not a decision to score.

    Counting it would either inflate or deflate the rate depending on how ties fell, and the point
    of the metric is the share of *decisions* the dispatcher gets right.
    """
    negatives = [pair for pair in PAIRS if pair.correct_variant is None]
    assert negatives, "this grid should contain negative pairs, or the denominator rule is untested"

    _, total = top1_accuracy(PAIRS, ARTIFACT, lexical_similarity)

    assert total == len(PAIRS) - len(negatives)


def test_a_program_with_no_variant_is_not_a_candidate() -> None:
    """A `None` variant must not enter the crossing, for the reason the negatives exist.

    It would compare equal to a negative pair's `correct_variant` and score as a win for the pairs
    where *nothing* should fire. The library quarantines such a program on load for the same reason
    it cannot be scored here (issues #66, #69).
    """
    variantless = PROGRAMS[0].model_copy(update={"variant": None})

    candidates = program_text_candidates([*PROGRAMS, variantless])

    assert None not in candidates
    assert len(candidates) == len(PROGRAMS)


# --- the measurement's mechanics, on the real scorer -------------------------


def test_a_scorer_that_cannot_discriminate_scores_one_half() -> None:
    """Every score equal: no ranking, so the AUC is 0.5 by definition.

    The floor matters because it is what a pointless scorer earns, and a probe that reported 0.0 for
    it would be reporting an inverted ranking instead. A constant is the control that shows it.
    """

    def constant(query: str, candidate: str) -> float:
        return 0.5

    assert discrimination_auc(PAIRS, ARTIFACT, constant) == pytest.approx(0.5)


def test_inverting_a_scorers_scores_inverts_its_auc() -> None:
    """The complement property, which is what proves the AUC reads the scores.

    If the number came from the pairs rather than from what the scorer returned, an inverted scorer
    would score the same. It cannot. The inversion wraps the real scorer rather than replacing it.
    """

    def inverted(query: str, candidate: str) -> float:
        return -lexical_similarity(query, candidate)

    forward = discrimination_auc(PAIRS, ARTIFACT, lexical_similarity)
    backward = discrimination_auc(PAIRS, ARTIFACT, inverted)

    assert forward is not None and backward is not None
    assert backward == pytest.approx(1.0 - forward)


def test_the_crossings_include_negatives() -> None:
    """No correct resolution means every resolution is wrong.

    That is the half an always-fires scorer fails.
    """
    scores, positives = discrimination_scores(PAIRS, ARTIFACT, lexical_similarity)

    assert scores and len(scores) == len(positives)
    assert len(scores) == len(PAIRS) * len(ARTIFACT)
    assert any(positives) and not all(positives), "the probe needs both classes to compute an AUC"


def test_a_single_class_reports_none_rather_than_zero() -> None:
    """`roc_auc` refuses one class, and `None` is not 0.0: unmeasured is not measured-zero."""
    # Built directly rather than by filtering pairs: crossing one pair with several candidates
    # always produces both classes, because at most one candidate can be correct for it. One pair
    # against only its own correct resolution is the single-class case.
    pair = next(candidate for candidate in PAIRS if candidate.correct_variant is not None)
    only_correct = {pair.correct_variant: ARTIFACT[pair.correct_variant]}

    assert discrimination_auc([pair], only_correct, lexical_similarity) is None


def test_comparing_scorers_gives_each_the_same_pairs() -> None:
    """A comparison is only a comparison if the denominators match."""
    by_intent = {
        intent.name: program_text_candidates(gold_programs(intent.name))
        for intent in ambiguous_intents()
    }
    findings = compare_scorers(
        {"lexical": lexical_similarity, "constant": lambda q, c: 0.0}, by_intent
    )

    assert [finding.scorer for finding in findings] == ["constant", "lexical"]
    assert len({finding.pairs for finding in findings}) == 1
    assert len({finding.comparisons for finding in findings}) == 1
    assert all(finding.pairs > 0 and finding.comparisons > 0 for finding in findings)


def test_the_probe_seeds_are_not_the_pre_registered_plan() -> None:
    """Named separately so nobody reads an exploratory figure as the eval split."""
    from precondition_library.bench.splits import EVAL_SEEDS, TUNE_SEEDS

    assert not set(PROBE_SEEDS) & set(EVAL_SEEDS)
    assert not set(PROBE_SEEDS) & set(TUNE_SEEDS)
    assert roc_auc([1.0, 0.0], [True, False]) == 1.0


def test_the_gold_programs_are_real_programs_with_variants() -> None:
    """A guard on the data the real tests rest on: three resolutions, each naming themselves."""
    assert len(PROGRAMS) == len(INTENT.variants)
    assert {program.variant for program in PROGRAMS} == {variant.id for variant in INTENT.variants}
    assert all(isinstance(program, Program) for program in PROGRAMS)
