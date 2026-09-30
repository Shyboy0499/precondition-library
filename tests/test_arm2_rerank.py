"""Arm 2's optional second stage: retrieve the top k, rerank, then threshold (ADR-0011).

Issue #4 asks for arm 2's "top-k rerank before selection". The first-stage scorer
retrieves the top `rerank_k` admitted programs, a second `Similarity` rescores them, and
the reranker's score is the one the threshold judges and the dispatch records. Without a
reranker arm 2 is exactly what it was. Scorers here are fakes with known orderings, so
every assertion is about the mechanism, not about lexical overlap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider, store_programs
from test_episode_runner import DISCARD_SEED, _discard_program

from precondition_library.bench.coverage import arm2_outcomes
from precondition_library.bench.ledger import Arm, OccurrenceRole
from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.run import _arm2_usage, run_episode
from precondition_library.library import Library
from precondition_library.program import Predicate, ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.similarity import SimilarityUsage, lexical_similarity
from precondition_library.tasks.registry import ambiguous_intents
from precondition_library.tasks.state_grid import STATE_GRID

_FIRST = {"alpha": 0.9, "beta": 0.5, "gamma": 0.2}
_RERANK = {"alpha": 0.3, "beta": 0.6, "gamma": 0.95}


def _by_word(table: dict[str, float]):
    def score(_query: str, candidate: str) -> float:
        return next(value for word, value in table.items() if word in candidate)

    return score


def _program(word: str, variant: str):
    """A stored program whose text contains `word`, so the fake scorers can find it."""
    return _discard_program(
        id=f"prog-{word}",
        variant=variant,
        preconditions=[
            Predicate(
                name="marker",
                description=f"the {word} program",
                probe=(
                    'test "$(git rev-list --count {upstream_remote}/{upstream_branch}..HEAD)" -gt 0'
                ),
            )
        ],
        status=ProgramStatus.ADMITTED,
    )


def _library(tmp_path: Path, **kwargs) -> Library:
    store_programs(
        tmp_path / "lib",
        [_program("alpha", "discard"), _program("beta", "merge"), _program("gamma", "rebase")],
    )
    return Library(
        tmp_path / "lib",
        similarity=_by_word(_FIRST),
        evaluate_preconditions=evaluate_preconditions,
        **kwargs,
    )


def _signature() -> TaskSignature:
    state = next(iter(STATE_GRID["sync_fork_with_upstream"].values()))
    assert isinstance(state, StateFingerprint)
    return TaskSignature(intent="sync my fork", fingerprint=state, target=".")


def test_without_a_reranker_the_first_stage_decides(tmp_path: Path) -> None:
    ranked = _library(tmp_path).match_semantic(_signature())
    assert [item.program.id for item in ranked] == ["prog-alpha", "prog-beta", "prog-gamma"]
    assert ranked[0].score == 0.9


def test_the_reranker_decides_among_the_retrieved_candidates(tmp_path: Path) -> None:
    ranked = _library(tmp_path, reranker=_by_word(_RERANK)).match_semantic(_signature())
    assert [item.program.id for item in ranked] == ["prog-gamma", "prog-beta", "prog-alpha"]
    assert ranked[0].score == 0.95, "the reranker's score is the one recorded"


def test_only_the_top_k_are_reranked(tmp_path: Path) -> None:
    """With k=2, gamma is never retrieved, however much the reranker would like it."""
    library = _library(tmp_path, reranker=_by_word(_RERANK), rerank_k=2)
    ranked = library.match_semantic(_signature())
    assert [item.program.id for item in ranked] == ["prog-beta", "prog-alpha"]


def test_the_threshold_judges_the_rerankers_score(tmp_path: Path) -> None:
    """A strong first-stage score cannot carry a candidate the reranker scores low."""
    library = _library(tmp_path, reranker=_by_word({"alpha": 0.05, "beta": 0.05, "gamma": 0.05}))
    assert library.match_semantic(_signature()) == []


def test_rerank_k_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rerank_k"):
        Library(tmp_path, rerank_k=0)


class _Metered:
    def __init__(self, tokens: int) -> None:
        self._tokens = tokens

    def __call__(self, query: str, candidate: str) -> float:
        return 0.5

    def usage(self) -> SimilarityUsage:
        return SimilarityUsage(tokens=self._tokens, calls=1)


def test_the_rerankers_spend_is_metered_with_the_seams_and_never_twice(tmp_path: Path) -> None:
    reranker = _Metered(40)
    both = Library(tmp_path, similarity=_Metered(7), reranker=reranker)
    assert _arm2_usage(both) == SimilarityUsage(tokens=47, calls=2)
    same = Library(tmp_path, similarity=reranker, reranker=reranker)
    assert _arm2_usage(same) == SimilarityUsage(tokens=40, calls=1)


def test_a_row_records_rerank_k_only_when_a_reranker_ran(tmp_path: Path) -> None:
    def replay_row(reranker) -> int | None:
        root = tmp_path / ("with" if reranker else "without")
        store_programs(root, [_discard_program(status=ProgramStatus.ADMITTED)])
        library = Library(root, evaluate_preconditions=evaluate_preconditions, reranker=reranker)
        record = run_episode(
            Arm.SEMANTIC,
            "diverged",
            DISCARD_SEED,
            1,
            role=OccurrenceRole.VARIANT,
            provider=FakeProvider(raises=AssertionError("a replay must not call the model")),
            library=library,
            model="fake",
        )
        assert record.fired_variant == "discard"
        return record.rerank_k

    assert replay_row(lexical_similarity) == 3
    assert replay_row(None) is None


def test_the_pair_level_adapter_reranks_the_same_way() -> None:
    intent = next(i for i in ambiguous_intents() if i.name == "sync_fork_with_upstream")
    pairs = labelled_pairs(intent, list(STATE_GRID[intent.name].values()), [0])[:1]
    candidates = {"discard": "alpha", "merge": "beta", "rebase": "gamma"}

    (plain,) = arm2_outcomes(pairs, candidates, _by_word(_FIRST))
    (reranked,) = arm2_outcomes(pairs, candidates, _by_word(_FIRST), reranker=_by_word(_RERANK))
    (narrow,) = arm2_outcomes(
        pairs, candidates, _by_word(_FIRST), reranker=_by_word(_RERANK), rerank_k=2
    )
    assert (plain.fired_variant, plain.score) == ("discard", 0.9)
    assert (reranked.fired_variant, reranked.score) == ("rebase", 0.95)
    assert (narrow.fired_variant, narrow.score) == ("merge", 0.6)
