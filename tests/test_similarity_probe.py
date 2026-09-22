"""The discrimination probe measures a scorer, and it can tell scorers apart (#104, #116).

A measurement nobody has seen separate a known-good from a known-bad scorer is not a measurement.
These tests pin the two ends: a scorer that cannot discriminate scores 0.5, and one that ranks the
same scores backwards scores exactly the complement. Between them they say the AUC is computed from
what the scorer returned rather than from the pairs.

The probe reports the two request regimes separately and never pools them (#104). The informed
regime is the headline baseline -- the wording nearly gives the resolution away, so a high score
there is the boundary condition rather than a mechanism win -- and the uninformed regime is the
plumbing tripwire `bench/textcontrol.py` designed, chance by construction. The single-mapping
functions require a `regime` for that reason, and `compare_scorers` returns one row per (regime,
scorer). The figures are hand-written gold on probe seeds 0-3, **not** the pre-registered split.

**The tests that matter most are the real ones**, added after #116: they use the hand-written
gold programs, `library._program_text` and the shipped `lexical_similarity`, with no stand-ins, and
they assert the two candidate sources **disagree**. That disagreement is what the probe's first
version missed -- it measured each resolution's `rationale` rather than the artifact a dispatcher
scores, and reported 0.6755 pooled where the artifact scored 0.5340 pooled (on the informed regime
the comparison is 0.9618 against 0.6007; the artifact's figure moves when the gold descriptions do,
which is why the printed test below is the measurement). A test asserting the sources differ would
have caught it on the day, so one exists now.

The two synthetic scorers below are controls, not stand-ins for project code: the seam is a
`Protocol` the project injects by design, and a constant is the only way to show what the floor
looks like. Everything else here runs the real thing.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable

import pytest
from conftest import gold_programs, percent

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.similarity_probe import (
    PROBE_SEEDS,
    REGIMES,
    Regime,
    compare_scorers,
    discrimination_auc,
    discrimination_scores,
    program_text_candidates,
    rationale_candidates,
    regime_of,
    top1_accuracy,
)
from precondition_library.bench.textcontrol import roc_auc
from precondition_library.library import _program_text
from precondition_library.program import Program
from precondition_library.similarity import Similarity, lexical_similarity, tokenize
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
    difference is not small. Measured on the informed regime, the baseline: the artifact scores
    0.6007 against the rationale's 0.9618 on `sync_fork_with_upstream`. A future edit that swapped
    one source for the other would show up here as a changed number rather than as a quietly wrong
    baseline. The regime is fixed to informed so the guard is about the text and not the channel.
    """
    artifact_auc = discrimination_auc(PAIRS, ARTIFACT, lexical_similarity, regime="informed")
    rationale_auc = discrimination_auc(PAIRS, RATIONALE, lexical_similarity, regime="informed")

    assert artifact_auc is not None and rationale_auc is not None
    print(
        f"\n  informed regime of {INTENT.name}:"
        f"\n  artifact (_program_text): AUC={artifact_auc:.4f}"
        f" top-1={top1_accuracy(PAIRS, ARTIFACT, lexical_similarity, regime='informed')}"
    )
    print(
        f"  rationale (diagnostic)  : AUC={rationale_auc:.4f}"
        f" top-1={top1_accuracy(PAIRS, RATIONALE, lexical_similarity, regime='informed')}"
    )

    assert rationale_auc - artifact_auc > 0.15, (
        "the two candidate sources are supposed to differ materially; if they no longer do, the "
        "texts changed and #116's finding needs re-measuring rather than this bound loosening"
    )


def test_the_artifact_baseline_is_reported_not_gated() -> None:
    """The baseline number, printed with its denominators and asserted only to be well formed.

    Deliberately not asserted against a threshold: it is an exploratory probe figure, and pinning it
    would turn a measurement into a claim (ADR-0003 rejected exactly that). What is asserted is that
    the measurement is usable -- the AUC is a number in range, and top-1 counts exactly the informed
    pairs that have a correct answer. The informed regime is the baseline; the uninformed regime is
    the tripwire printed in `test_the_informed_baseline_is_per_intent_crossings_added_up`.
    """
    informed = [pair for pair in PAIRS if regime_of(pair) == "informed"]
    auc = discrimination_auc(informed, ARTIFACT, lexical_similarity, regime="informed")
    decided, total = top1_accuracy(informed, ARTIFACT, lexical_similarity, regime="informed")

    assert auc is not None and 0.0 <= auc <= 1.0
    assert total == sum(1 for pair in informed if pair.correct_variant is not None)
    assert total == len(informed), "informed wording exists only where a resolution does"
    assert 0 <= decided <= total

    print(
        f"\n  shipped lexical scorer on the gold artifact, informed: AUC={auc:.4f},"
        f" strict top-1 {decided}/{total}, across {len(informed)} pairs"
        f" (chance for {len(ARTIFACT)} candidates = {1 / len(ARTIFACT):.2f})"
    )


def test_top1_counts_only_pairs_that_have_a_correct_answer() -> None:
    """The denominator: a negative pair has no right program, so it is not a decision to score.

    Counting it would either inflate or deflate the rate depending on how ties fell, and the point
    of the metric is the share of *decisions* the dispatcher gets right. The negative pairs are the
    uninformed regime's, so the denominator rule is measured there.
    """
    uninformed = [pair for pair in PAIRS if regime_of(pair) == "uninformed"]
    negatives = [pair for pair in uninformed if pair.correct_variant is None]
    assert negatives, "this grid should contain negative pairs, or the denominator rule is untested"

    _, total = top1_accuracy(uninformed, ARTIFACT, lexical_similarity, regime="uninformed")

    assert total == len(uninformed) - len(negatives)


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

    assert discrimination_auc(PAIRS, ARTIFACT, constant, regime="informed") == pytest.approx(0.5)


def test_inverting_a_scorers_scores_inverts_its_auc() -> None:
    """The complement property, which is what proves the AUC reads the scores.

    If the number came from the pairs rather than from what the scorer returned, an inverted scorer
    would score the same. It cannot. The inversion wraps the real scorer rather than replacing it.
    """

    def inverted(query: str, candidate: str) -> float:
        return -lexical_similarity(query, candidate)

    forward = discrimination_auc(PAIRS, ARTIFACT, lexical_similarity, regime="informed")
    backward = discrimination_auc(PAIRS, ARTIFACT, inverted, regime="informed")

    assert forward is not None and backward is not None
    assert backward == pytest.approx(1.0 - forward)


def test_the_crossings_include_negatives() -> None:
    """No correct resolution means every resolution is wrong -- the half an always-fires scorer
    fails.

    They occur in the uninformed regime: informed wording exists only where a resolution does, so an
    informed crossing is always one positive among the candidates and can never be all-negative.
    """
    uninformed = [pair for pair in PAIRS if regime_of(pair) == "uninformed"]
    informed = [pair for pair in PAIRS if regime_of(pair) == "informed"]
    scores, positives = discrimination_scores(
        PAIRS, ARTIFACT, lexical_similarity, regime="uninformed"
    )

    assert scores and len(scores) == len(positives)
    assert len(scores) == len(uninformed) * len(ARTIFACT)
    assert any(positives) and not all(positives), "the probe needs both classes to compute an AUC"

    _, informed_positives = discrimination_scores(
        PAIRS, ARTIFACT, lexical_similarity, regime="informed"
    )
    assert len(informed_positives) == len(informed) * len(ARTIFACT)
    assert sum(informed_positives) == len(informed), (
        "each informed pair has exactly one correct resolution among the candidates, so the "
        "informed regime has no all-negative pair"
    )


def test_a_single_class_reports_none_rather_than_zero() -> None:
    """`roc_auc` refuses one class, and `None` is not 0.0: unmeasured is not measured-zero."""
    # Built directly rather than by filtering pairs: crossing one pair with several candidates
    # always produces both classes, because at most one candidate can be correct for it. One pair
    # against only its own correct resolution is the single-class case.
    pair = next(candidate for candidate in PAIRS if candidate.correct_variant is not None)
    only_correct = {pair.correct_variant: ARTIFACT[pair.correct_variant]}

    assert (
        discrimination_auc([pair], only_correct, lexical_similarity, regime=regime_of(pair)) is None
    )


def test_comparing_scorers_gives_each_the_same_pairs() -> None:
    """A comparison is only a comparison if the denominators match -- per regime, not pooled."""
    by_intent = {
        intent.name: program_text_candidates(gold_programs(intent.name))
        for intent in ambiguous_intents()
    }
    findings = compare_scorers(
        {"lexical": lexical_similarity, "constant": lambda q, c: 0.0}, by_intent
    )

    assert [(finding.regime, finding.scorer) for finding in findings] == [
        ("informed", "constant"),
        ("informed", "lexical"),
        ("uninformed", "constant"),
        ("uninformed", "lexical"),
    ]
    for regime in REGIMES:
        rows = [finding for finding in findings if finding.regime == regime]
        assert len({finding.pairs for finding in rows}) == 1
        assert len({finding.comparisons for finding in rows}) == 1
        assert len({finding.decidable for finding in rows}) == 1
        assert all(finding.pairs > 0 and finding.comparisons > 0 for finding in rows)


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


# --- the ambiguous subset, which is what the baseline has to be quoted over ----


def _all_intent_candidates() -> dict[str, dict[str, str]]:
    return {
        intent.name: program_text_candidates(gold_programs(intent.name))
        for intent in ambiguous_intents()
    }


def test_the_regimes_partition_the_pairs() -> None:
    """Every pair belongs to exactly one regime, and together they are the whole set.

    The partition is what makes "per regime" well defined. It is also where the construction shows:
    the informed regime has no negative pairs, because informed wording exists only where a
    resolution does, while the uninformed regime carries all of them as the tripwire.
    """
    for intent in ambiguous_intents():
        pairs = labelled_pairs(intent, list(STATE_GRID[intent.name].values()), list(PROBE_SEEDS))
        informed = [pair for pair in pairs if regime_of(pair) == "informed"]
        uninformed = [pair for pair in pairs if regime_of(pair) == "uninformed"]

        assert informed and uninformed, "both channels have to be present to be measured"
        assert len(informed) + len(uninformed) == len(pairs)
        assert set(map(id, informed)).isdisjoint(map(id, uninformed))
        assert {pair.informed for pair in pairs} == {True, False}
        assert all(pair.correct_variant is not None for pair in informed)
        assert any(pair.correct_variant is None for pair in uninformed)


def test_the_informed_baseline_is_per_intent_crossings_added_up() -> None:
    """The headline baseline is the informed regime, and it is not one intent's number.

    The regime correction (#104): the informed channel is where the wording nearly gives the
    resolution away, so it is the boundary condition the baseline has to be quoted at, and the
    uninformed channel is chance by construction and is reported beside it as the plumbing tripwire.
    Within the informed regime the two intents differ by more than 0.2 AUC, so a single number taken
    from one describes neither; pooling is only valid over per-intent crossings, which is what
    `compare_scorers` does and what the guard in `_require_one_intent` refuses to fake with one
    merged mapping.

    These are hand-written gold programs on the probe seeds 0-3 -- **not** the pre-registered split.
    Reproduce the table with
    `pytest tests/test_similarity_probe.py -q -s -k informed_baseline`.
    """
    by_intent = _all_intent_candidates()
    findings = {
        (finding.regime, finding.scorer): finding
        for finding in compare_scorers({"lexical": lexical_similarity}, by_intent)
    }

    print("\n  shipped lexical scorer on the gold artifact, per regime:")
    print("  (hand-written gold programs, probe seeds 0-3; NOT the pre-registered split)")
    per_intent: dict[str, dict[str, tuple[float | None, int, int, int]]] = {}
    for regime in REGIMES:
        per_intent[regime] = {}
        for intent in ambiguous_intents():
            pairs = [
                pair
                for pair in labelled_pairs(
                    intent, list(STATE_GRID[intent.name].values()), list(PROBE_SEEDS)
                )
                if regime_of(pair) == regime
            ]
            auc = discrimination_auc(
                pairs, by_intent[intent.name], lexical_similarity, regime=regime
            )
            decided, decidable = top1_accuracy(
                pairs, by_intent[intent.name], lexical_similarity, regime=regime
            )
            per_intent[regime][intent.name] = (auc, decided, decidable, len(pairs))
            rendered = "None" if auc is None else f"{auc:.4f}"
            print(
                f"    {regime:11s} {intent.name:28s} AUC={rendered}"
                f" top-1 {decided}/{decidable} ({percent(decided, decidable)})"
            )
        found = findings[(regime, "lexical")]
        rendered = "None" if found.auc is None else f"{found.auc:.4f}"
        print(
            f"    {regime:11s} {'BOTH (pooled per intent)':28s} AUC={rendered}"
            f" top-1 {found.decided}/{found.decidable}"
            f" ({percent(found.decided, found.decidable)}), chance for 3 candidates = 33%"
        )

    for regime in REGIMES:
        found = findings[(regime, "lexical")]
        rows = per_intent[regime]
        assert found.decided == sum(decided for _, decided, _, _ in rows.values())
        assert found.decidable == sum(decidable for _, _, decidable, _ in rows.values())
        assert found.pairs == sum(length for _, _, _, length in rows.values())
        assert found.auc is not None and 0.0 <= found.auc <= 1.0

    informed = findings[("informed", "lexical")]
    uninformed = findings[("uninformed", "lexical")]
    assert informed.decidable == informed.pairs, (
        "informed wording exists only where a resolution does, so the informed regime has no "
        "negatives"
    )
    assert uninformed.decidable < uninformed.pairs, (
        "the negative pairs belong in `pairs`, not `decidable`; they are the uninformed tripwire"
    )


def test_the_candidate_texts_pairwise_similarity_is_reported() -> None:
    """How near-interchangeable the three candidates of an intent are -- the cause, printed.

    This is the manipulation check for a rewrite of the gold descriptions: making each
    program's `_program_text` state what distinguishes it should *lower* this number, and
    if it does not, the texts are still interchangeable whatever changed. It is reported
    rather than gated, because it is an exploratory figure and a threshold would make it a
    claim (ADR-0003 rejected exactly that for the probe's numbers).

    What is asserted is only that the measurement is well formed: every intent contributes
    at least the two candidates a comparison needs, and every mean is a similarity in
    `[0, 1]`. The embedding's reading of the same texts lives in
    `tests/test_embedding_similarity.py`, which needs the pinned model.
    """
    by_intent = _all_intent_candidates()

    print("\n  candidate-vs-candidate mean pairwise similarity (lexical Jaccard):")
    means: dict[str, float] = {}
    for intent in ambiguous_intents():
        texts = list(by_intent[intent.name].values())
        pairs = list(itertools.combinations(texts, 2))
        means[intent.name] = sum(lexical_similarity(*pair) for pair in pairs) / len(pairs)
        print(
            f"    {intent.name:28s} {means[intent.name]:.4f} over {len(pairs)} pairs "
            f"({len(texts)} candidates)"
        )

    assert set(means) == {intent.name for intent in ambiguous_intents()}
    assert all(len(by_intent[name]) >= 2 for name in means)
    assert all(0.0 <= value <= 1.0 for value in means.values())


def test_crossing_two_intents_is_refused_rather_than_scored() -> None:
    """One candidate mapping cannot describe two intents, and the mistake must not return a number.

    Variant ids are unique only within an intent, so merging two intents' candidates and scoring
    all their pairs against the merged mapping crosses each pair with resolutions that are not its
    own. It does not fail -- it returns a plausible figure (0.7722 and 12/24 on the informed regime
    where the per-intent crossings give 0.6172 and 15/24), which is how it reached a draft of this
    scope. Refusing is the only safe answer, because the caller's intent cannot be recovered from
    the mapping.
    """
    by_intent = _all_intent_candidates()
    names = [intent.name for intent in ambiguous_intents()]
    merged = {
        variant: text for candidates in by_intent.values() for variant, text in candidates.items()
    }
    both_pairs = [
        pair
        for intent in ambiguous_intents()
        for pair in labelled_pairs(
            intent, list(STATE_GRID[intent.name].values()), list(PROBE_SEEDS)
        )
    ]

    for call in (
        lambda: discrimination_scores(both_pairs, merged, lexical_similarity, regime="informed"),
        lambda: discrimination_auc(both_pairs, merged, lexical_similarity, regime="informed"),
        lambda: top1_accuracy(both_pairs, merged, lexical_similarity, regime="informed"),
    ):
        with pytest.raises(ValueError) as caught:
            call()
        for name in names:
            assert name in str(caught.value)


def test_the_weighting_alternatives_do_not_fix_the_argmax() -> None:
    """IDF weighting reorders slightly and picks *fewer* right answers, so it is not the fix.

    Measured per regime on the committed gold and the probe's seeds: on the informed baseline the
    shipped Jaccard scores 0.6172 and 15-of-24 against IDF-weighted Jaccard's 0.6380 and 13-of-24
    and IDF-weighted cosine's 0.6658 and 13-of-24; in the uninformed regime, chance by construction,
    it is 8-of-24 against 6-of-24. Both alternatives raise the AUC and lower strict top-1, which is
    the metric dispatch acts on.

    The reason IDF cannot be adopted anyway is structural: it needs a corpus, and arm 2's seam is
    a two-argument `(query, candidate) -> float` with nowhere to put one. `compare_scorers` takes
    such a scorer, so this measures the alternatives in its own loop instead -- the corpus is each
    intent's own candidate texts, which is the only corpus dispatch has at scoring time.

    Both alternatives are built from the project's own `tokenize`, so the comparison is about the
    weighting and not about a second tokenisation.
    """
    by_intent = _all_intent_candidates()

    def idf_of(texts: list[str]) -> dict[str, float]:
        document_frequency: dict[str, int] = {}
        for text in texts:
            for token in set(tokenize(text)):
                document_frequency[token] = document_frequency.get(token, 0) + 1
        return {token: math.log(len(texts) / count) for token, count in document_frequency.items()}

    def weighted(idf: dict[str, float], *, cosine: bool) -> Similarity:
        def score(query: str, candidate: str) -> float:
            query_tokens, candidate_tokens = set(tokenize(query)), set(tokenize(candidate))
            if not query_tokens or not candidate_tokens:
                return 0.0
            shared = query_tokens & candidate_tokens
            if cosine:
                left = math.sqrt(sum(idf.get(t, 0.0) ** 2 for t in query_tokens))
                right = math.sqrt(sum(idf.get(t, 0.0) ** 2 for t in candidate_tokens))
                # Every token on one side occurring in all three candidates leaves no weighted
                # evidence to normalise by, which is the same situation as an empty text.
                if not left or not right:
                    return 0.0
                return sum(idf.get(t, 0.0) ** 2 for t in shared) / (left * right)
            union = sum(idf.get(t, 0.0) for t in query_tokens | candidate_tokens)
            return sum(idf.get(t, 0.0) for t in shared) / union if union else 0.0

        return score

    def measure(
        regime: Regime, scorer_for: Callable[[dict[str, float]], Similarity]
    ) -> tuple[float, int, int]:
        scores: list[float] = []
        positives: list[bool] = []
        decided = decidable = 0
        for name, candidates in by_intent.items():
            pairs = [
                pair
                for pair in labelled_pairs(
                    next(i for i in ambiguous_intents() if i.name == name),
                    list(STATE_GRID[name].values()),
                    list(PROBE_SEEDS),
                )
                if regime_of(pair) == regime
            ]
            scorer = scorer_for(idf_of(list(candidates.values())))
            for pair in pairs:
                for variant_id, text in candidates.items():
                    scores.append(scorer(pair.task_text, text))
                    positives.append(pair.correct_variant == variant_id)
                if pair.correct_variant is not None:
                    decidable += 1
                    ranked = sorted(
                        ((scorer(pair.task_text, t), v) for v, t in candidates.items()),
                        reverse=True,
                    )
                    if ranked[0][0] > ranked[1][0] and ranked[0][1] == pair.correct_variant:
                        decided += 1
        return roc_auc(scores, positives), decided, decidable

    print("\n  shipped artifact text, per regime over the whole ambiguous subset:")
    print("  (hand-written gold programs, probe seeds 0-3; NOT the pre-registered split)")
    measured: dict[tuple[Regime, str], tuple[float, int, int]] = {}
    alternatives: tuple[tuple[str, Callable[[dict[str, float]], Similarity]], ...] = (
        ("lexical Jaccard (shipped)", lambda _idf: lexical_similarity),
        ("IDF-weighted Jaccard", lambda idf: weighted(idf, cosine=False)),
        ("IDF-weighted cosine", lambda idf: weighted(idf, cosine=True)),
    )
    for regime in REGIMES:
        for label, scorer_for in alternatives:
            found = measure(regime, scorer_for)
            measured[(regime, label)] = found
            auc, decided, decidable = found
            print(f"    {regime:11s} {label:26s} AUC={auc:.4f} top-1 {decided}/{decidable}")

    for regime in REGIMES:
        shipped = measured[(regime, "lexical Jaccard (shipped)")]
        jaccard = measured[(regime, "IDF-weighted Jaccard")]
        cosine = measured[(regime, "IDF-weighted cosine")]
        assert shipped[1] >= jaccard[1] and shipped[1] >= cosine[1], (
            f"IDF was rejected because it lowers the argmax accuracy on the {regime} regime; if it "
            f"now raises it, the rejection needs re-measuring rather than this assertion removing"
        )
