"""The primary metric's raw material.

Every rate this repository reports has to come with its denominator, and the
label has to be a property of the state rather than of anybody's behaviour.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.pairs import (
    decision_is_correct,
    denominator_report,
    label,
    labelled_pairs,
    positive_subset,
)
from precondition_library.tasks.registry import INTENTS, ambiguous_intents

SEEDS = list(range(12))


def test_label_is_a_property_of_state_not_wording(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    states = list(state_grid["sync_fork_with_upstream"].values())
    pairs = labelled_pairs(intent, states, SEEDS)
    by_state: dict[int, set[str | None]] = {}
    for pair in pairs:
        by_state.setdefault(id(pair.state), set()).add(pair.correct_variant)
    assert all(len(answers) == 1 for answers in by_state.values())


def test_benign_states_produce_negative_pairs(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    benign = [state_grid["sync_fork_with_upstream"]["benign_nothing_local"]]
    pairs = labelled_pairs(intent, benign, SEEDS)
    assert pairs, "the generator must not silently produce nothing"
    assert all(pair.is_negative for pair in pairs)
    assert all(pair.correct_variant is None for pair in pairs)


def test_firing_a_program_is_wrong_on_a_benign_state(state_grid) -> None:
    """The label a dispatcher is graded against: on a benign state, every
    program is the wrong program."""
    intent = INTENTS["sync_fork_with_upstream"]
    pair = label(
        intent, seed=1, state=state_grid["sync_fork_with_upstream"]["benign_nothing_local"]
    )
    assert decision_is_correct(pair, candidate_variant="rebase") is False
    assert decision_is_correct(pair, candidate_variant="discard") is False


def test_wrong_resolution_is_wrong_and_right_one_is_right(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    state = state_grid["sync_fork_with_upstream"]["overlapping_files"]  # merge is correct
    pair = label(intent, seed=3, state=state)
    assert decision_is_correct(pair, candidate_variant="merge") is True
    assert decision_is_correct(pair, candidate_variant="rebase") is False
    assert decision_is_correct(pair, candidate_variant="discard") is False


def test_generator_rejects_empty_input(state_grid) -> None:
    intent = INTENTS["sync_fork_with_upstream"]
    with pytest.raises(ValueError, match="produced no pairs"):
        labelled_pairs(intent, [], SEEDS)
    with pytest.raises(ValueError, match="produced no pairs"):
        labelled_pairs(intent, list(state_grid["sync_fork_with_upstream"].values()), [])


def test_denominators_add_up(state_grid) -> None:
    pairs = []
    for intent in ambiguous_intents():
        pairs.extend(labelled_pairs(intent, list(state_grid[intent.name].values()), SEEDS))
    report = denominator_report(pairs)
    assert report["pairs"] == report["positive"] + report["negative"]
    assert report["ambiguous"] <= report["pairs"]
    assert report["positive"] == len(positive_subset(pairs))
    assert report["negative"] > 0, "a denominator report with no negatives hides half the test"


def test_every_ambiguous_intent_contributes_pairs(state_grid) -> None:
    for intent in ambiguous_intents():
        states = list(state_grid[intent.name].values())
        pairs = labelled_pairs(intent, states, SEEDS)
        informed_states = sum(intent.uses_informed_wording(state) for state in states)
        assert len(pairs) == (len(states) + informed_states) * len(SEEDS)
