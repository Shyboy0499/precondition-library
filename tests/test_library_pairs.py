"""Figure 1's pair outcomes come from a library's own matchers on real sandboxes (#162).

The first real Figure 1 needed a driver outside the repository, because nothing turned a
compiled library into per-pair outcomes. `bench.library_pairs` is that driver. These tests
pin that it dispatches through the library -- its admitted filter, its unthresholded
similarity, its intent key -- that the pairs are the ones ADR-0022 records, and that the
result feeds `bench.primary` as it stands.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.bench.coverage import vacuous_reason
from precondition_library.bench.library_pairs import (
    FAULT_FREE,
    INTENT_KEY,
    SOFT_VOTE,
    is_pair,
    library_pair_outcomes,
)
from precondition_library.bench.pairs import label
from precondition_library.bench.primary import primary_report
from precondition_library.library import Library
from precondition_library.program import Program, ProgramStatus
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.faults.diverged import INTENT as SYNC_INTENT
from precondition_library.tasks.state_grid import STATE_GRID

FAULTS = ["diverged", "submodule_moved"]
SEEDS = [0, 1]


def _admit(library: Library, program: Program, **provenance: str) -> None:
    """Store a candidate and admit it, the way a build does after the gate passes."""
    library.add(
        program.model_copy(update={"provenance": program.provenance.model_copy(update=provenance)})
    )
    library.set_status(program.id, ProgramStatus.ADMITTED)


def _gold_library(root: Path, **kwargs) -> Library:
    library = Library(root, evaluate_preconditions=evaluate_preconditions, **kwargs)
    for intent in ("sync_fork_with_upstream", "restore_submodule_state"):
        for program in gold_programs(intent):
            _admit(library, program)
    return library


@pytest.fixture(scope="module")
def gold_outcomes(tmp_path_factory):
    library = _gold_library(tmp_path_factory.mktemp("lib") / "gold", threshold=0.9)
    before = library.library_hash()
    outcomes = library_pair_outcomes(library, FAULTS, SEEDS)
    assert library.library_hash() == before, "the library is read, never written"
    return outcomes


def test_each_intent_is_paired_with_its_own_state_and_the_fault_free_sandbox(
    gold_outcomes,
) -> None:
    """Per seed and intent: the fault-free sandbox and the intent's own fault's state."""
    environments = [entry.environment for entry in gold_outcomes.pairs]
    assert len(environments) == len(SEEDS) * 2 * len(FAULTS)
    assert environments.count(FAULT_FREE) == len(SEEDS) * len(FAULTS)
    for name in (gold_outcomes.arm2, gold_outcomes.arm3, gold_outcomes.soft_vote):
        assert len(name) == len(environments)
    assert all(not entry.pair.informed for entry in gold_outcomes.pairs), "uninformed only"


def test_another_faults_unlabelled_state_is_not_a_pair(gold_outcomes) -> None:
    """Neither measured intent labels the other's states, so none is paired with it.

    Pairing a submodule request with a diverged repository would score arm 3 -- which
    reads only the environment, by design -- for firing `merge` where no episode would
    ever ask it to choose (ADR-0022).
    """
    own = {"sync_fork_with_upstream": "diverged", "restore_submodule_state": "submodule_moved"}
    for entry in gold_outcomes.pairs:
        if entry.environment == FAULT_FREE:
            assert entry.pair.correct_variant is None, entry
        else:
            assert entry.environment == own[entry.pair.intent], entry
            assert entry.pair.correct_variant is not None, entry


def test_gold_arm3_is_the_labelling_rule_so_the_comparison_is_vacuous(gold_outcomes) -> None:
    """Hand-written gold agrees with the rules everywhere -- the guard must say so."""
    assert vacuous_reason(gold_outcomes.arm3) is not None
    assert [o.fired_variant for o in gold_outcomes.arm3] == [
        entry.pair.correct_variant for entry in gold_outcomes.pairs
    ]


def test_arm2_is_unthresholded_whatever_the_library_is_configured_at(gold_outcomes) -> None:
    """The library's 0.9 floor is not applied: every pair has a top program and a score."""
    assert all(o.fired_variant is not None for o in gold_outcomes.arm2)
    assert any(o.score is not None and o.score < 0.9 for o in gold_outcomes.arm2)


def test_the_soft_vote_carries_its_score_and_gold_has_no_request_key(gold_outcomes) -> None:
    assert all(o.score is not None for o in gold_outcomes.soft_vote)
    assert all(o.fired_variant is None for o in gold_outcomes.intent_key), (
        "gold's provenance names no request, so the intent key never fires on it"
    )


def test_the_outcomes_feed_the_primary_report(gold_outcomes) -> None:
    report = primary_report(
        gold_outcomes.arm2, gold_outcomes.arm3, baselines=gold_outcomes.baselines()
    )
    assert report.pairs == len(gold_outcomes.pairs)
    assert report.vacuous is not None
    assert [b.name for b in report.baselines] == [SOFT_VOTE, INTENT_KEY]


def test_only_admitted_programs_fire_and_the_intent_key_reads_the_request(tmp_path) -> None:
    """The library's own filter and arm 2c's own rule, not a re-implementation."""
    library = Library(tmp_path / "lib", evaluate_preconditions=evaluate_preconditions)
    merge = next(p for p in gold_programs() if p.variant == "merge")
    _admit(library, merge, compiled_from_task=SYNC_INTENT.task_text(0))
    candidate = next(p for p in gold_programs() if p.variant == "rebase")
    library.add(candidate)  # gold's own status: candidate, so never dispatched

    outcomes = library_pair_outcomes(library, ["diverged"], [0])

    fired = {o.fired_variant for o in [*outcomes.arm2, *outcomes.arm3, *outcomes.soft_vote]}
    assert "rebase" not in fired
    assert {o.fired_variant for o in outcomes.intent_key} == {"merge"}, (
        "every seed-0 pair sends seed 0's request, which is the key merge was compiled from"
    )


def test_refusals(tmp_path) -> None:
    with pytest.raises(ValueError, match="predicate evaluator"):
        library_pair_outcomes(Library(tmp_path / "a"), FAULTS, SEEDS)
    evaluated = Library(tmp_path / "b", evaluate_preconditions=evaluate_preconditions)
    with pytest.raises(ValueError, match="cannot be measured"):
        library_pair_outcomes(evaluated, ["lockfile_conflict"], SEEDS)
    with pytest.raises(ValueError, match="no seeds"):
        library_pair_outcomes(evaluated, FAULTS, [])


def test_an_overlap_state_is_a_pair_and_an_unlabelled_foreign_one_is_not() -> None:
    """The rule on its own, since no measured fault today injects another's overlap."""
    grid = STATE_GRID["sync_fork_with_upstream"]
    overlap = label(SYNC_INTENT, 0, grid["overlapping_files"], uninformed=True)
    benign = label(SYNC_INTENT, 0, grid["benign_nothing_local"], uninformed=True)
    assert overlap.correct_variant == "merge" and benign.correct_variant is None

    assert is_pair("lockfile_conflict", SYNC_INTENT, overlap), "a labelled foreign state"
    assert not is_pair("submodule_moved", SYNC_INTENT, benign), "an unlabelled foreign state"
    assert is_pair("diverged", SYNC_INTENT, benign), "the intent's own fault, labelled or not"
    assert is_pair(FAULT_FREE, SYNC_INTENT, benign)
