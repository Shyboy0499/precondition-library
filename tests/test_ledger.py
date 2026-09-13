"""Misfire and success must be recorded independently, or the metric hides itself.

The failure this project exists to reduce is a program that fires on a state it
does not fit. Such an episode usually still *succeeds*, because the wrong fire
falls back to the agent. An episode record with a single outcome field cannot
express that -- it must choose one of the two -- so correctness is stored as
facts and the verdicts are derived from them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from precondition_library.bench.ledger import Arm, EpisodeRecord
from precondition_library.program import EpisodeOutcome


def _record(**overrides) -> EpisodeRecord:
    base = {
        "arm": Arm.PRECONDITION,
        "task_id": "sync_fork_with_upstream/seed-1",
        "fault_type": "diverged",
        "occurrence_index": 1,
        "seed": 1,
        "tokens_in": 0,
        "tokens_out": 0,
        "llm_calls": 0,
        "wall_clock_s": 0.0,
        "outcome": EpisodeOutcome.FALLBACK,
        "model": "test",
        "correct_variant": "merge",
        "ground_truth_ok": True,
    }
    base.update(overrides)
    return EpisodeRecord(**base)


def test_the_quadrant_the_metric_exists_for() -> None:
    """Misfired and successful at once, which one outcome field cannot say."""
    record = _record(fired_variant="rebase", ground_truth_ok=True)
    assert record.misfired is True
    assert record.succeeded is True


def test_a_correct_fire_that_still_failed() -> None:
    """The other diagonal: the right program, and the environment did not get there."""
    record = _record(fired_variant="merge", ground_truth_ok=False)
    assert record.misfired is False
    assert record.succeeded is False


def test_refusing_to_fire_is_not_a_misfire() -> None:
    """Firing nothing can be right on a benign state, and is never a wrong fire."""
    record = _record(correct_variant=None, fired_variant=None, ground_truth_ok=True)
    assert record.misfired is False
    assert record.succeeded is True


def test_firing_on_a_benign_state_is_a_misfire() -> None:
    record = _record(correct_variant=None, fired_variant="rebase", ground_truth_ok=False)
    assert record.misfired is True


def test_ground_truth_cannot_be_omitted() -> None:
    """`None` is a meaningful ground truth, so a missing one must not read as it."""
    payload = _record().model_dump()
    del payload["correct_variant"]
    with pytest.raises(ValidationError, match="correct_variant"):
        EpisodeRecord(**payload)
