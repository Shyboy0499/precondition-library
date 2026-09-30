"""Whole-run replicates and the instance-clustered bootstrap (issue #6, ADR-0012).

#6 asks for k >= 3 repeats per (fault, seed, arm) and seed-level uncertainty. Pinned here:

* `run_replicates` re-runs the whole plan from scratch per replicate -- its own ledger,
  and in the online mode its own libraries -- and every row says which replicate it is.
* `cluster_bootstrap` resamples **instances**, each carrying all its rows across arms
  and replicates, so repeats never count as independent observations; it is seeded, so
  the interval reproduces exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider, make_record
from test_episode_runner import (
    DISCARD_SEED,
    SECOND_DISCARD_SEED,
    _completion,
    _discard_program,
    _reply_text,
    _resolves_discard,
)

from precondition_library.bench.ledger import Arm, OccurrenceRole
from precondition_library.bench.report import cluster_bootstrap, read_replicates
from precondition_library.bench.run import run_episode, run_replicates
from precondition_library.library import Library
from precondition_library.program import EpisodeOutcome
from precondition_library.tasks.faults import FAULTS

# --- replicates -------------------------------------------------------------------


def test_each_replicate_runs_the_plan_from_scratch(tmp_path: Path) -> None:
    """Two replicates, each solving and compiling for itself: no shared library."""
    turns = [*_resolves_discard(), _completion(_reply_text(_discard_program()))]
    ledgers = run_replicates(
        out_dir=tmp_path,
        replicates=2,
        arms=[Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=1,
        seeds=[DISCARD_SEED],
        model="fake",
        provider=FakeProvider(*turns, *turns),
    )

    assert ledgers == [
        tmp_path / "replicate-1" / "ledger.jsonl",
        tmp_path / "replicate-2" / "ledger.jsonl",
    ]
    rows = read_replicates(ledgers)
    assert [row.replicate for row in rows] == [1, 2]
    assert all(row.fired_variant is None for row in rows), "each replicate starts empty"
    for replicate in (1, 2):
        library = Library(tmp_path / f"replicate-{replicate}" / "library-precondition")
        assert len(library.program_ids()) == 1, "each replicate compiled its own program"


def test_replicates_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        run_replicates(out_dir=tmp_path, replicates=0)
    with pytest.raises(ValueError, match="sets each replicate"):
        run_replicates(out_dir=tmp_path, replicates=1, out=tmp_path / "x.jsonl")


def test_an_invalid_row_keeps_its_replicate(tmp_path: Path, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated sandbox failure")

    monkeypatch.setattr("precondition_library.bench.run.build_sandbox", _boom)
    record = run_episode(
        Arm.PRECONDITION,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(),
        library=Library(tmp_path / "lib"),
        model="fake",
        replicate=3,
    )
    assert record.outcome is EpisodeOutcome.INVALID
    assert record.replicate == 3


# --- the bootstrap ------------------------------------------------------------------


def _row(arm: Arm, seed: int, fired: str | None, *, replicate: int = 1, correct: str = "merge"):
    return make_record(
        arm=arm,
        seed=seed,
        fired_variant=fired,
        correct_variant=correct,
        replicate=replicate,
    )


def test_seeds_that_draw_one_instance_are_one_cluster() -> None:
    """Seeds 1 and 28 build the same `diverged` instance, so they resample together."""
    spec = FAULTS["diverged"]
    assert spec.instance_for_seed(DISCARD_SEED) == spec.instance_for_seed(SECOND_DISCARD_SEED)
    result = cluster_bootstrap(
        [
            _row(Arm.SEMANTIC, DISCARD_SEED, "merge"),
            _row(Arm.PRECONDITION, SECOND_DISCARD_SEED, "merge"),
        ],
        resamples=10,
    )
    assert result.clusters == 1


def test_replicates_add_rows_but_never_clusters() -> None:
    rows = [
        _row(arm, seed, "merge", replicate=replicate)
        for replicate in (1, 2, 3)
        for arm in (Arm.SEMANTIC, Arm.PRECONDITION)
        for seed in (0, 2, 4)
    ]
    result = cluster_bootstrap(rows, resamples=10)
    assert result.rows == 18
    assert result.replicates == 3
    assert result.clusters == len({FAULTS["diverged"].instance_for_seed(s) for s in (0, 2, 4)})


def test_the_point_estimate_is_per_fire_and_the_interval_is_seeded() -> None:
    rows = [
        _row(Arm.SEMANTIC, 0, "merge"),
        _row(Arm.SEMANTIC, 2, "rebase", correct="discard"),
        _row(Arm.SEMANTIC, 4, None),
        _row(Arm.PRECONDITION, 0, "merge"),
        _row(Arm.PRECONDITION, 2, "discard", correct="discard"),
        _row(Arm.PRECONDITION, 4, None),
    ]
    first = cluster_bootstrap(rows, resamples=500)
    again = cluster_bootstrap(rows, resamples=500)
    assert (first.arm2_mismatch.numerator, first.arm2_mismatch.denominator) == (1, 2)
    assert (first.arm3_mismatch.numerator, first.arm3_mismatch.denominator) == (0, 2)
    assert first.difference == pytest.approx(0.5)
    assert first.interval is not None and first.interval == again.interval
    assert first.interval.low <= first.difference <= first.interval.high


def test_a_resample_where_an_arm_never_fires_is_skipped_not_scored() -> None:
    rows = [_row(Arm.SEMANTIC, 0, "merge"), _row(Arm.PRECONDITION, 2, None)]
    result = cluster_bootstrap(rows, resamples=50)
    assert result.difference is None, "arm 3 fired nothing, so it has no per-fire mismatch"
    assert result.skipped == 50, "arm 3 fires in no resample, so every one is skipped"
    assert result.interval is None


def test_replays_and_arm_1_are_left_out() -> None:
    rows = [
        _row(Arm.SEMANTIC, 0, "merge"),
        _row(Arm.PRECONDITION, 0, "merge"),
        make_record(arm=Arm.REACT, seed=0),
        make_record(
            arm=Arm.PRECONDITION,
            seed=0,
            fired_variant="rebase",
            occurrence_role=OccurrenceRole.REPLAY,
        ),
    ]
    result = cluster_bootstrap(rows, resamples=10)
    assert result.rows == 2
    assert result.arm3_mismatch.numerator == 0
