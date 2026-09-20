"""Misfire and success must be recorded independently, or the metric hides itself.

The failure this project exists to reduce is a program that fires on a state it
does not fit. Such an episode usually still *succeeds*, because the wrong fire
falls back to the agent. An episode record with a single outcome field cannot
express that -- it must choose one of the two -- so correctness is stored as
facts and the verdicts are derived from them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_record as _record
from pydantic import ValidationError

from precondition_library.bench.ledger import EpisodeRecord, append, read
from precondition_library.program import EpisodeOutcome


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


def test_guard_refusals_and_compile_failures_are_separate_fields(tmp_path: Path) -> None:
    """A refusal rate must not pick up a compile failure (issue #60).

    A guard refusal is a safety finding; a compile failure is a compile-quality
    one. One field carrying both made a refusal rate include "the reply was not a
    YAML mapping" -- a row where no guard was ever consulted. Each degradation now
    names its own cause, and the guard refusal rate is a grouping over
    `refusal_reason` alone, with no second field read to disambiguate it.
    """
    rows = [
        _record(
            seed=1,
            outcome=EpisodeOutcome.REFUSAL,
            refusal_reason="refused network: curl to attacker.invalid",
        ),
        _record(
            seed=2,
            outcome=EpisodeOutcome.FALLBACK,
            compile_failure_reason="the reply was not a YAML mapping, so it is not a Program",
        ),
        _record(seed=3, outcome=EpisodeOutcome.INVALID, invalid_reason="sandbox build failed"),
    ]
    path = tmp_path / "ledger.jsonl"
    for row in rows:
        append(path, row)
    stored = read(path)

    # Each row is distinguishable by which reason field it carries.
    assert [row.refusal_reason is not None for row in stored] == [True, False, False]
    assert [row.compile_failure_reason is not None for row in stored] == [False, True, False]
    assert [row.invalid_reason is not None for row in stored] == [False, False, True]

    # The rate is computable from `refusal_reason` alone, and it does not drift
    # when a compile failure or an invalid row sits in the same ledger.
    refusals = [row for row in stored if row.refusal_reason is not None]
    assert len(refusals) / len(stored) == pytest.approx(1 / 3)
    assert [row.outcome for row in refusals] == [EpisodeOutcome.REFUSAL]


def test_the_change_surface_round_trips_and_none_differs_from_empty(tmp_path: Path) -> None:
    """`None` is "not applied"; `()` is "applied, and nothing may change" (issue #96).

    The two are different facts and the ledger has to keep them apart across a write and a
    read. An empty surface that was applied is the *strictest* declaration a fault can make
    -- `branch_renamed` declares it -- while `None` means no surface was ever handed to the
    check. A round trip that collapsed either into the other would turn a deliberate "no
    committed change" into "nobody looked", or the reverse.
    """
    path = tmp_path / "ledger.jsonl"
    applied = _record(seed=1, change_surface=("app.py", "docs/readme.md"))
    empty = _record(seed=2, change_surface=())
    unchecked = _record(seed=3, change_surface=None)
    for record in (applied, empty, unchecked):
        append(path, record)

    stored = read(path)

    assert [row.change_surface for row in stored] == [
        ("app.py", "docs/readme.md"),
        (),
        None,
    ]
    assert stored[0].change_surface == ("app.py", "docs/readme.md")
    assert stored[1].change_surface == ()
    assert stored[1].change_surface is not None, "an applied empty surface is not a missing one"
    assert stored[2].change_surface is None
    assert stored == [applied, empty, unchecked]
