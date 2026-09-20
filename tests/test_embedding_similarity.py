"""Arm 2's embedding seam, and the measurement that decides whether to swap it in (#104).

The scorer in `precondition_library.bench.embedding_similarity` is real code behind the same
`Similarity` seam the lexical proxy sits behind, so these tests run the **real** pinned model on
the **real** gold programs. There are no stand-ins: a fake embedding would test the fake, and the
question here is what the real one does on this fault family.

That makes the model a test dependency, and CI installs only the dev extra. So the tests below
carry `pytest.mark.skipif` and are declared in `tests/test_declared_state.py`, which is how this
repository makes a skip visible and assigns it an owner. The skip reason names what is missing --
the `embedding` extra or the pinned revision's cache -- rather than leaving a bare "skipped" in the
report.

**What is asserted and what is only printed.** The contract properties are asserted because they
are the seam's promises: a `[0, 1]` score, 1 for identical text, bit-exact repeats, and an honest
usage report. The discrimination figures are **printed, not gated** -- a threshold on an
exploratory probe number would turn it into a claim (CONTRIBUTING rule 1), and ADR-0003 rejected
exactly that. What *is* asserted about the measurement is that it is well formed and that both
scorers saw the same pairs, because a comparison whose denominators differ is not a comparison.
If the embedding is worse, the printed table says so; it is not hidden by an absent assertion.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping

import pytest
from conftest import gold_programs

from precondition_library.bench.embedding_similarity import (
    MODEL_ID,
    MODEL_REVISION,
    EmbeddingSimilarity,
    cosine_to_unit,
)
from precondition_library.bench.pairs import LabelledPair, labelled_pairs
from precondition_library.bench.similarity_probe import (
    PROBE_SEEDS,
    compare_scorers,
    discrimination_auc,
    program_text_candidates,
    top1_accuracy,
)
from precondition_library.similarity import (
    ReportsUsage,
    Similarity,
    SimilarityUsage,
    lexical_similarity,
    similarity_usage,
)
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.state_grid import STATE_GRID

PARAPHRASE = ("discard the commits", "throw away local history")
"""ADR-0002's own example: the same request in words that share no token."""


def _embedding_model_missing() -> str | None:
    """Why the real scorer cannot be built here, or `None` when it can.

    Both halves are needed. CI has no network **and** no model cache, so on CI the package is
    simply absent; a contributor who did install the extra but never downloaded the pinned
    revision hits the other half, and the tests must skip there too rather than attempting a
    download that cannot happen offline.
    """
    if importlib.util.find_spec("sentence_transformers") is None:
        return "the `embedding` extra (sentence-transformers) is not installed"
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError as error:  # pragma: no cover - only on a broken extra install
        return f"huggingface_hub, which the extra depends on, is not importable ({error})"
    cached = try_to_load_from_cache(MODEL_ID, "modules.json", revision=MODEL_REVISION)
    if not isinstance(cached, str):
        return f"{MODEL_ID}@{MODEL_REVISION} is not in the local HuggingFace cache"
    return None


_MODEL_MISSING = _embedding_model_missing()


@pytest.fixture(scope="module")
def scorer() -> EmbeddingSimilarity:
    """One loaded model for the module, because the seam loads once and the probe is slow.

    `usage()` accumulates across tests that share this instance, which is deliberate: the
    measurement test reports a before/after delta rather than an absolute, so the shared counter
    cannot turn one test's traffic into another's number.
    """
    return EmbeddingSimilarity()


def _pairs_for(intent_name: str) -> list[LabelledPair]:
    return labelled_pairs(
        next(intent for intent in ambiguous_intents() if intent.name == intent_name),
        list(STATE_GRID[intent_name].values()),
        list(PROBE_SEEDS),
    )


def _candidates_by_intent() -> dict[str, dict[str, str]]:
    return {
        intent.name: program_text_candidates(gold_programs(intent.name))
        for intent in ambiguous_intents()
    }


def _intent_figures(
    scorer: Similarity,
    candidates_by_intent: Mapping[str, Mapping[str, str]],
) -> dict[str, tuple[float | None, int, int]]:
    """`{intent: (AUC, strict top-1, decidable)}` for one scorer, per intent.

    ADR-0003 requires the per-intent breakdown beside any pooled figure, so this is
    the shape the table is printed in.
    """
    figures: dict[str, tuple[float | None, int, int]] = {}
    for intent in ambiguous_intents():
        pairs = _pairs_for(intent.name)
        candidates = candidates_by_intent[intent.name]
        decided, decidable = top1_accuracy(pairs, candidates, scorer)
        figures[intent.name] = (discrimination_auc(pairs, candidates, scorer), decided, decidable)
    return figures


# --- the seam's contract, on the real model ----------------------------------


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_the_embedding_scorer_satisfies_both_protocols(scorer: EmbeddingSimilarity) -> None:
    """`Similarity` and `ReportsUsage` are structural, so the check is behavioural plus `mypy`.

    Neither Protocol is `runtime_checkable` -- `isinstance` would raise -- so the runtime half is
    that the value is the two-argument callable the seam declares and that the optional usage
    protocol answers through the project's own `similarity_usage`. The annotation below is the
    static half: `mypy src` fails if the instance stops satisfying either Protocol.
    """
    seam: Similarity = scorer
    reporter: ReportsUsage = scorer

    assert callable(seam)
    assert isinstance(similarity_usage(seam), SimilarityUsage)
    assert isinstance(reporter.usage(), SimilarityUsage)
    assert similarity_usage(seam) == reporter.usage()


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_the_paraphrase_beats_the_lexical_proxy(
    scorer: EmbeddingSimilarity,
) -> None:
    """The proxy's stated ceiling, and the reason this module exists.

    `similarity.py` documents that "discard the commits" and "throw away local history" score
    zero against each other because the proxy reads surface form. The embedding reads meaning, so
    it must not. The bound is asserted because the model is pinned: the number is a property of
    this revision, not an exploratory probe figure that might move.
    """
    lexical = lexical_similarity(*PARAPHRASE)
    embedding = scorer(*PARAPHRASE)

    print(f"\n  paraphrase {PARAPHRASE!r}: lexical={lexical:.4f} embedding={embedding:.4f}")

    assert lexical == 0.0, "the lexical proxy is supposed to have no signal on this pair"
    assert embedding > 0.2, (
        "the embedding must read the paraphrase as similar; if this fails on the pinned revision, "
        "the model or the mapping changed and the measurement needs re-taking"
    )


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_identical_texts_score_exactly_one(scorer: EmbeddingSimilarity) -> None:
    """`1.0 == identical` is the contract's anchor; a mapping that broke it would break thresholds.

    Checked on several real gold artifact texts rather than one string, so the property is not a
    coincidence of a particular token length.
    """
    texts = [
        text for candidates in _candidates_by_intent().values() for text in candidates.values()
    ]
    assert texts, "no candidate texts to check"

    for text in texts:
        assert scorer(text, text) == pytest.approx(1.0, abs=1e-6)


def test_the_unit_mapping_covers_the_whole_cosine_range() -> None:
    """The `[-1, 1] -> [0, 1]` map is affine and onto, and 1.0 is still identical.

    A pure function, so this runs everywhere and needs no skip. It pins the arithmetic the model
    test can only sample -- no real pair produces a negative cosine here, so the model test alone
    would never reach the lower half. `cosine_to_unit(0.0) == 0.5` is the consequence worth
    seeing: orthogonal texts land mid-scale, not at zero.
    """
    assert cosine_to_unit(-1.0) == 0.0
    assert cosine_to_unit(0.0) == 0.5
    assert cosine_to_unit(1.0) == 1.0
    assert cosine_to_unit(0.25) == pytest.approx(0.625)


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_every_score_stays_in_the_unit_interval(scorer: EmbeddingSimilarity) -> None:
    """Cosine is `[-1, 1]`; the seam promises `[0, 1]`, so the mapping has to hold on real text.

    The range is printed as well as asserted, because the *position* is a finding: this model
    scores even unrelated short English texts with a positive cosine, so the mapped scores sit
    above the midpoint and use a narrow band. That is the mapping's consequence, not a defect,
    and it is why a lexical threshold does not transfer.
    """
    queries = [pair.task_text for pair in _pairs_for("sync_fork_with_upstream")]
    candidates = [
        text for candidates in _candidates_by_intent().values() for text in candidates.values()
    ]

    scores = [scorer(query, candidate) for query in queries for candidate in candidates]

    assert scores
    assert all(0.0 <= score <= 1.0 for score in scores)
    assert min(scores) < max(scores), "constant scores would make the range check vacuous"

    print(f"\n  real pair scores: min={min(scores):.4f} max={max(scores):.4f} over {len(scores)}")


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_usage_counts_encode_calls_and_charges_no_tokens() -> None:
    """A local model bills no provider tokens, and saying so is the point of the field.

    `tokens=0` is measured, not a placeholder: this implementation talks to a local model and no
    provider. `calls` counts encode calls, which is the provider-traffic reading
    `SimilarityUsage.calls` settled on -- one per scored pair here, because one pair is one batch.
    A fresh instance is used so the initial zero is observable.
    """
    fresh = EmbeddingSimilarity()

    assert similarity_usage(fresh) == SimilarityUsage(tokens=0, calls=0)

    fresh(*PARAPHRASE)
    fresh("a", "b")

    assert similarity_usage(fresh) == SimilarityUsage(tokens=0, calls=2)


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_repeated_scoring_is_bit_exact_any_order(scorer: EmbeddingSimilarity) -> None:
    """The determinism ADR-0002 requires, asserted with `==` rather than a tolerance.

    A batch of 2 and a batch of 1 differ by 8.2e-08 on this machine because different tensor
    shapes reach different BLAS kernels, so a scorer whose batch composition varied with call
    order would not be reproducible. This interleaves unrelated pairs between the two scorings of
    the same pair: if the implementation let batch shape track the calls around it, the numbers
    would drift and `==` would fail.
    """
    first = scorer(*PARAPHRASE)
    scorer("an unrelated query", "an unrelated candidate")
    scorer("another pair entirely", "with different lengths of text")
    again = scorer(*PARAPHRASE)

    assert first == again, (
        f"repeated scoring diverged ({first!r} against {again!r}); the seam is required to be "
        f"bit-exact, which is why it fixes the batch shape at one pair per call"
    )


# --- the measurement: embedding against the shipped lexical scorer ------------


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned model cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_the_embedding_is_measured_against_lexical(
    scorer: EmbeddingSimilarity,
) -> None:
    """The comparison #104 exists to produce, over the whole ambiguous subset.

    Run with `-s` to see it:

        .venv/bin/python -m pytest tests/test_embedding_similarity.py -s -q \\
            -k measured_against_lexical

    Pooled figures come from `compare_scorers`, which is the probe's own comparison and pools
    per-intent crossings; the per-intent table beside them is ADR-0003's requirement, because the
    two ambiguous intents differ enough that the pooled number describes neither. The figures are
    printed and **not gated** -- gating an exploratory figure would make it a claim -- and the
    lexical row is the ADR-0003 baseline re-measured on the same run, so the two rows are
    comparable rather than quoted from different occasions.
    """
    by_intent = _candidates_by_intent()
    before = scorer.usage()

    findings = {
        finding.scorer: finding
        for finding in compare_scorers(
            {"embedding": scorer, "lexical": lexical_similarity}, by_intent
        )
    }

    print("\n  arm 2's seam on the ambiguous subset, pooled (`compare_scorers`):")
    for name in ("lexical", "embedding"):
        found = findings[name]
        auc = "None" if found.auc is None else f"{found.auc:.4f}"
        print(
            f"    {name:10s} AUC={auc} strict top-1 {found.decided}/{found.decidable} "
            f"({found.decided / found.decidable:.0%}) across {found.pairs} pairs, "
            f"{found.comparisons} crossings"
        )

    print("  by intent (ADR-0003 requires the breakdown beside any pooled figure):")
    per_scorer = {
        "lexical": _intent_figures(lexical_similarity, by_intent),
        "embedding": _intent_figures(scorer, by_intent),
    }
    for intent in ambiguous_intents():
        for name in ("lexical", "embedding"):
            auc, decided, decidable = per_scorer[name][intent.name]
            rendered = "None" if auc is None else f"{auc:.4f}"
            print(
                f"    {intent.name:28s} {name:10s} AUC={rendered} "
                f"top-1 {decided}/{decidable} ({decided / decidable:.0%})"
            )

    after = scorer.usage()
    print(
        f"  the embedding seam spent for this measurement: "
        f"tokens={after.tokens - before.tokens} calls={after.calls - before.calls}"
    )

    lexical, embedding = findings["lexical"], findings["embedding"]
    for found in (lexical, embedding):
        assert found.auc is not None and 0.0 <= found.auc <= 1.0
        assert 0 <= found.decided <= found.decidable < found.pairs, (
            "decidable is a strict subset of pairs: the negative pairs have no correct resolution"
        )

    assert lexical.pairs == embedding.pairs
    assert lexical.comparisons == embedding.comparisons
    assert lexical.decidable == embedding.decidable, (
        "the two scorers must be compared on the same decisions, or the comparison is not one"
    )
    for name in per_scorer:
        for auc, decided, decidable in per_scorer[name].values():
            assert (auc is None or 0.0 <= auc <= 1.0) and 0 <= decided <= decidable
