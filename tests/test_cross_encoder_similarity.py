"""Arm 2's cross-encoder seam (#104): the wrapper's contract, and the real model where it loads.

The wrapper's own promises -- a score in `(0, 1)` that keeps the model's order, one pair per model
call, a memo that changes the cost and not the score, zero provider tokens -- are tested against a
recording stand-in for the model, because they are properties of this module's code. What the
real reranker does on the gold programs is tested beside them and skips, declared in
`tests/test_declared_state.py`, where the `embedding` extra or the pinned revision is absent.
"""

from __future__ import annotations

import importlib.util
import math

import pytest
from conftest import gold_programs

from precondition_library.bench import cross_encoder_similarity as module
from precondition_library.bench.cross_encoder_similarity import (
    MODEL_ID,
    MODEL_REVISION,
    CrossEncoderSimilarity,
    logistic,
)
from precondition_library.bench.similarity_probe import program_text_candidates
from precondition_library.similarity import (
    ReportsUsage,
    Similarity,
    SimilarityUsage,
    similarity_usage,
)


class _Recording:
    """Stands in for `CrossEncoder`: the logit is the candidate's length minus the query's."""

    def __init__(self) -> None:
        self.batches: list[list[tuple[str, str]]] = []

    def predict(self, pairs, *, batch_size, show_progress_bar, convert_to_numpy):
        self.batches.append(list(pairs))
        assert batch_size == len(pairs)
        return [float(len(c) - len(q)) for q, c in pairs]


@pytest.fixture
def recorded(monkeypatch) -> tuple[CrossEncoderSimilarity, _Recording]:
    model = _Recording()
    monkeypatch.setattr(module, "_load_model", lambda model_id, revision: model)
    return CrossEncoderSimilarity(), model


def test_the_score_is_the_logistic_of_the_logit_and_keeps_its_order(recorded) -> None:
    scorer, _ = recorded
    seam: Similarity = scorer
    reporter: ReportsUsage = scorer
    assert similarity_usage(seam) == reporter.usage()
    assert scorer("ab", "ab") == 0.5
    assert scorer("abc", "a") == pytest.approx(1 / (1 + math.e**2))
    assert 0.0 < scorer("aaaa", "a") < scorer("a", "a") < scorer("a", "aaaa") < 1.0


def test_the_logistic_does_not_overflow_at_either_end() -> None:
    assert logistic(1000.0) == 1.0 and logistic(-1000.0) == 0.0
    assert logistic(2.0) + logistic(-2.0) == pytest.approx(1.0)


def test_each_model_call_scores_one_pair_and_a_repeat_is_memoised(recorded) -> None:
    scorer, model = recorded
    first = scorer("request", "program text")
    scorer("request", "another program")
    assert scorer("request", "program text") == first
    assert model.batches == [[("request", "program text")], [("request", "another program")]]
    assert scorer.usage() == SimilarityUsage(tokens=0, calls=2)


def test_the_query_and_the_candidate_are_not_swapped(recorded) -> None:
    scorer, model = recorded
    scorer("the request", "the program")
    assert model.batches == [[("the request", "the program")]]


def test_score_many_is_one_model_call_per_request_and_memoised(recorded) -> None:
    scorer, model = recorded
    first = scorer.score_many("q", ["a", "bbb"])
    assert first == [logistic(0.0), logistic(2.0)]
    assert scorer.score_many("q", ["a", "bbb"]) == first
    assert scorer.score_many("q", []) == []
    assert model.batches == [[("q", "a"), ("q", "bbb")]]
    assert scorer.usage().calls == 1


def test_batched_and_pairwise_scores_are_cached_apart(recorded) -> None:
    scorer, model = recorded
    scorer.score_many("q", ["a"])
    scorer("q", "a")
    assert model.batches == [[("q", "a")], [("q", "a")]]


def test_arm_2_scores_each_request_as_one_batch(tmp_path, recorded) -> None:
    from precondition_library.library import Library
    from precondition_library.program import ProgramStatus
    from precondition_library.signatures import StateFingerprint, TaskSignature

    state = StateFingerprint(
        dirty_worktree=False,
        branch="main",
        upstream_ahead=1,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
    )
    scorer, model = recorded
    library = Library(tmp_path / "lib", similarity=scorer, threshold=0.0)
    for program in gold_programs()[:3]:
        candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
        library.add(candidate)
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    signature = TaskSignature(intent="sync my fork", fingerprint=state, target="")
    matched = library.match_semantic(signature, limit=10)
    assert len(model.batches) == 1 and len(model.batches[0]) == 3
    assert [item.score for item in matched] == sorted(
        (item.score for item in matched), reverse=True
    )


def _reranker_missing() -> str | None:
    if importlib.util.find_spec("sentence_transformers") is None:
        return "the `embedding` extra (sentence-transformers) is not installed"
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(MODEL_ID, "config.json", revision=MODEL_REVISION)
    if not isinstance(cached, str):
        return f"{MODEL_ID}@{MODEL_REVISION} is not in the local HuggingFace cache"
    return None


_MODEL_MISSING = _reranker_missing()


@pytest.mark.skipif(
    _MODEL_MISSING is not None,
    reason="the `embedding` extra or the pinned reranker cache is unavailable here and the "
    "tests run offline; CI has neither, so the real scorer cannot load (#104)",
)
def test_the_real_reranker_scores_the_gold_texts_in_the_unit_interval_and_repeatably() -> None:
    scorer = CrossEncoderSimilarity()
    texts = program_text_candidates(gold_programs())
    request = "my edits are in files upstream did not touch"
    first = {variant: scorer(request, text) for variant, text in texts.items()}
    again = CrossEncoderSimilarity()
    assert {variant: again(request, text) for variant, text in texts.items()} == first
    assert all(0.0 < score < 1.0 for score in first.values())
    assert scorer.model_id == MODEL_ID and scorer.revision == MODEL_REVISION
