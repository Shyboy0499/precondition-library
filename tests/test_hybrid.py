"""The hybrid arm's arithmetic, and the record it is derived from (issue #265).

Most of this file builds `LibraryPair` records by hand: a hybrid decision is a walk down a recorded
ranking with an accepted set beside it, so the walk's rules -- the gate is per candidate, `k` caps
the walk, the retrieval floor stops it, a negative pair can never fire -- are testable without a
sandbox. One test does build real sandboxes, because the record the walk reads has to be the library
own matchers' output and not something this test agrees with itself about.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.bench.coverage import detectable_difference
from precondition_library.bench.hybrid import (
    KS,
    NO_FLOOR,
    WORDING_LIMIT,
    hybrid_decision,
    hybrid_points,
    run_hybrid,
    text,
    threshold_grid,
    widest_zero_mismatch,
)
from precondition_library.bench.library_pairs import LibraryPair, library_pair_outcomes
from precondition_library.bench.live import LivePlan
from precondition_library.bench.pairs import LabelledPair
from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.similarity import lexical_similarity
from precondition_library.tasks.state_grid import declared_state


def _pair(
    accepted: tuple[str, ...],
    ranked: tuple[tuple[str, str | None, float], ...],
    *,
    correct: str | None = "rebase",
    acceptable: tuple[str, ...] = ("rebase",),
) -> LibraryPair:
    """One recorded pair: what the state accepts and the request's text ranking."""
    from precondition_library.bench.library_pairs import RankedProgram

    state = declared_state()
    return LibraryPair(
        pair=LabelledPair(
            intent="sync_fork_with_upstream",
            seed=0,
            state=state,
            correct_variant=correct,
            acceptable_variants=acceptable,
            task_text="bring my branch up to date",
            ambiguous=True,
            informed=False,
        ),
        environment="diverged",
        accepted=accepted,
        ranked=tuple(
            RankedProgram(id=program_id, variant=variant, score=score)
            for program_id, variant, score in ranked
        ),
    )


def test_the_gate_fires_the_best_ranked_program_the_state_accepts() -> None:
    """The walk takes the first accepted candidate, not the most specific one: text rank wins."""
    pair = _pair(
        accepted=("b",),
        ranked=(("a", "discard", 0.9), ("b", "rebase", 0.8), ("c", "merge", 0.7)),
    )
    assert hybrid_decision(pair, k=None, threshold=NO_FLOOR) == "rebase"

    same = _pair(
        accepted=("c",),
        ranked=(("a", "discard", 0.9), ("b", "rebase", 0.8), ("c", "merge", 0.7)),
    )
    assert hybrid_decision(same, k=None, threshold=NO_FLOOR) == "merge"


def test_the_top_k_caps_how_far_down_the_walk_the_gate_looks() -> None:
    pair = _pair(
        accepted=("c",),
        ranked=(("a", "discard", 0.9), ("b", "rebase", 0.8), ("c", "merge", 0.7)),
    )
    assert hybrid_decision(pair, k=2, threshold=NO_FLOOR) is None
    assert hybrid_decision(pair, k=3, threshold=NO_FLOOR) == "merge"
    assert hybrid_decision(pair, k=10, threshold=NO_FLOOR) == "merge"


def test_the_retrieval_floor_stops_the_walk_at_the_first_score_below_it() -> None:
    pair = _pair(
        accepted=("b",),
        ranked=(("a", "discard", 0.9), ("b", "rebase", 0.4), ("c", "merge", 0.3)),
    )
    assert hybrid_decision(pair, k=None, threshold=0.5) is None
    assert hybrid_decision(pair, k=None, threshold=0.4) == "rebase"
    assert hybrid_decision(pair, k=None, threshold=NO_FLOOR) == "rebase"
    assert hybrid_decision(pair, k=None, threshold=0.35) == "rebase", "a candidate below the floor"


def test_a_negative_pair_can_never_fire_however_good_the_text_match() -> None:
    """The gate is per candidate, so a fault-free sandbox accepts nothing and the arm abstains."""
    pair = _pair(
        accepted=(),
        ranked=(("a", "discard", 1.0), ("b", "rebase", 0.99)),
        correct=None,
        acceptable=(),
    )
    assert hybrid_decision(pair, k=None, threshold=NO_FLOOR) is None


def test_the_grid_is_every_distinct_score_plus_no_floor() -> None:
    pairs = [
        _pair(("a",), (("a", "discard", 0.9), ("b", "rebase", 0.4))),
        _pair(("b",), (("b", "rebase", 0.4),)),
    ]
    grid = threshold_grid(pairs)
    assert grid == [0.9, 0.4, NO_FLOOR]


def test_the_family_has_one_point_per_k_and_floor() -> None:
    pairs = [_pair(("b",), (("a", "discard", 0.9), ("b", "rebase", 0.4)))]
    points = hybrid_points(pairs, ks=(1, None), thresholds=(0.5, NO_FLOOR))
    assert [(entry.k, entry.threshold) for entry in points] == [
        (1, 0.5),
        (1, NO_FLOOR),
        (None, 0.5),
        (None, NO_FLOOR),
    ]
    assert points[0].point.coverage.numerator == 0, "the floor keeps the accepted one out"
    assert points[1].point.coverage.numerator == 0, "and k=1 stops above it"
    assert points[3].point.coverage.numerator == 1, "uncapped and unfloored, it fires 'rebase'"
    assert points[3].point.mismatch.numerator == 0
    assert [entry.no_floor for entry in points] == [False, True, False, True]


def test_the_widest_zero_mismatch_point_carries_its_own_upper_limit() -> None:
    """The descriptive reading: the most fires a k reached at zero mis-fires, with the bound."""
    pairs = [
        # The state accepts the second-ranked program, so k decides whether this pair fires at all.
        _pair(
            ("a2",),
            (("a1", "discard", 0.9), ("a2", "rebase", 0.4)),
            correct="rebase",
            acceptable=("rebase",),
        ),
        _pair(("b",), (("b", "rebase", 0.4),)),
        _pair(("c",), (("c", "merge", 0.2),), correct="merge", acceptable=("merge",)),
    ]
    points = hybrid_points(pairs, ks=(None,), thresholds=(0.5, 0.3, NO_FLOOR))
    widest = widest_zero_mismatch(points)
    assert len(widest) == 1
    assert widest[0].k is None and widest[0].fires == 3, "no floor fires all three, none wrongly"
    assert widest[0].mismatch_upper is not None and 0.0 < widest[0].mismatch_upper < 1.0
    assert widest[0].threshold == NO_FLOOR

    capped = widest_zero_mismatch(hybrid_points(pairs, ks=(1,), thresholds=(NO_FLOOR,)))
    assert [entry.fires for entry in capped] == [2], "k=1 cannot reach the accepted runner-up"


def test_the_registered_grid_and_wording_are_what_the_spec_says() -> None:
    assert KS == (1, 2, 3, 5, 10, None)
    assert "optimistically biased" in WORDING_LIMIT
    assert detectable_difference(187, 187, base_rate=0.5) == pytest.approx(0.145, abs=0.001)


@pytest.fixture(scope="module")
def gold_root(tmp_path_factory) -> Path:
    """A frozen library of the gold `diverged` programs, admitted, for the sandbox tests."""
    root = tmp_path_factory.mktemp("hybrid-gold") / "library-two-sided"
    library = Library(root, similarity=lexical_similarity)
    for program in gold_programs():
        candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
        library.add(candidate)
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    return root


PLAN = LivePlan(episodes=False, online=False, faults=("diverged",), pair_seeds=(1,))


def test_the_record_carries_the_librarys_own_ranking_and_accepted_set(gold_root: Path) -> None:
    """The walk reads a record; the record has to be the library's matchers, not this test's idea.

    Pinned against arm 3's own decisions in the same pass: wherever arm 3 fired, the program whose
    variant it fired is in the recorded accepted set, and where it fired nothing the set is empty.
    That is the property the hybrid's walk depends on -- and it needs no second sandbox to check.
    """
    library = Library(gold_root, evaluate_preconditions=evaluate_preconditions)
    outcomes = library_pair_outcomes(library, ["diverged"], [1])
    recorded = [entry for entry in outcomes.pairs if entry.ranked]
    assert recorded, "the record has to carry the ranking, or the walk has nothing to read"
    assert all(len(entry.ranked) == len(library.load_all()) for entry in recorded), (
        "the full ranking, not a top-1 trim: the hybrid sweeps k over it"
    )
    assert any(entry.accepted for entry in recorded), "the diverged state accepts something"
    for entry, outcome in zip(outcomes.pairs, outcomes.arm3, strict=True):
        variants = {candidate.variant: candidate.id for candidate in entry.ranked}
        if outcome.fired_variant is None:
            assert entry.accepted == (), f"{entry.environment}: arm 3 fired nothing"
            continue
        assert variants[outcome.fired_variant] in entry.accepted, (
            f"{entry.environment}: the program arm 3 fired is not in the recorded accepted set"
        )
    assert all(entry.ranked or entry.environment for entry in outcomes.pairs), (
        "every pair records a ranking, even when it is empty for a negative"
    )
    for entry, arm2 in zip(outcomes.pairs, outcomes.arm2, strict=True):
        if arm2.fired_variant is None:
            continue
        # The wider limit may not have moved arm 2's own decision: it re-trims the same ranking.
        assert entry.ranked, "arm 2 fired, so the record carries a ranking"
        assert entry.ranked[0].variant == arm2.fired_variant, "arm 2 is still the ranking's top"
        assert entry.ranked[0].score == arm2.score, "and it still fires at its own top score"
        scores = [candidate.score for candidate in entry.ranked]
        assert scores == sorted(scores, reverse=True), "the record is in ranking order"


def test_the_hybrid_stage_writes_its_artifacts_and_refuses_a_used_directory(
    gold_root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run"
    summary = run_hybrid(
        gold_root,
        out,
        similarity=lexical_similarity,
        scorer_id={"scorer": "lexical"},
        source="a gold library",
        plan=PLAN,
        ks=(1, None),
        plot=False,
    )
    assert summary.library_hash_before == summary.library_hash_after
    assert summary.pairs == 2, "one clean environment and one diverged state, one intent each"
    assert (out / "hybrid.csv").is_file() and (out / "summary.txt").is_file()
    assert (out / "hybrid.json").is_file() and (out / "summary.json").is_file()
    rows = (out / "hybrid.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == summary.fired_points + 1, "one header, one row per point that fired"
    record = json.loads((out / "hybrid.json").read_text(encoding="utf-8"))
    assert record["library_hash"] == summary.library_hash_before
    assert record["matched"]["arm3"]["fires"] == summary.arm3_fires
    assert "hybrid at arm 3's coverage" in text(summary)
    saved = [
        LibraryPair.model_validate_json(line)
        for line in (out / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(saved) == summary.pairs, "one saved record per pair, so a reading needs no rebuild"

    with pytest.raises(ValueError, match="fresh directory"):
        run_hybrid(
            gold_root,
            out,
            similarity=lexical_similarity,
            scorer_id={"scorer": "lexical"},
            source="a gold library",
            plan=PLAN,
            ks=(1,),
            plot=False,
        )
