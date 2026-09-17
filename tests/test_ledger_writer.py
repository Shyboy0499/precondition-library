"""The ledger writer must not lose an episode that it reported as written.

Two properties carry the whole project's accounting. First, `append` flushes to
the operating system before returning, so a process killed after the call still
left the record on disk. Second, `read` refuses a torn ledger instead of
returning the lines before it: an episode dropped from the file is an episode
dropped from a denominator, and an incomplete list would be reported as a
smaller experiment rather than as a broken one.

These tests use `tmp_path`, never the repository's `bench/` directory.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import GIT_STATUS_AT_IMPORT, git_status_porcelain
from conftest import make_record as _record

from precondition_library.bench.ledger import (
    LedgerCorruptError,
    append,
    read,
)
from precondition_library.program import EpisodeOutcome

ROOT = Path(__file__).resolve().parents[1]


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    """Including the two required facts, a None fire, and the derived verdicts."""
    records = [
        _record(),
        # The quadrant the metric exists for: misfired and still successful.
        _record(
            seed=2,
            occurrence_index=2,
            fired_variant="rebase",
            ground_truth_ok=True,
        ),
        # A guard refusal: no fire, benign state, so not a misfire. `refusal_reason`
        # belongs to a `refusal` outcome; a compile failure would carry
        # `compile_failure_reason` instead (issue #60).
        _record(
            seed=3,
            occurrence_index=3,
            correct_variant=None,
            fired_variant=None,
            ground_truth_ok=True,
            outcome=EpisodeOutcome.REFUSAL,
            program_id="p-1",
            dispatch_score=0.87,
            admitted=True,
            refusal_reason="state already matches",
            cached_tokens_in=12,
            timed_out=True,
        ),
    ]

    path = tmp_path / "ledger.jsonl"
    for record in records:
        append(path, record)

    read_back = read(path)
    assert read_back == records
    for original, restored in zip(records, read_back, strict=True):
        assert restored.model_dump() == original.model_dump()
        # The facts survived as facts, and the verdicts are still derived.
        assert restored.correct_variant == original.correct_variant
        assert restored.ground_truth_ok == original.ground_truth_ok
        assert restored.misfired == original.misfired
        assert restored.succeeded == original.succeeded

    assert read_back[1].misfired is True
    assert read_back[1].succeeded is True
    assert read_back[2].fired_variant is None
    assert read_back[2].misfired is False
    assert read_back[2].succeeded is True


def test_one_line_per_record(tmp_path: Path) -> None:
    """A record with a newline inside a field must not become two lines."""
    records = [
        _record(seed=1),
        _record(seed=2, compile_failure_reason="first line\nsecond line"),
        _record(seed=3),
    ]
    path = tmp_path / "ledger.jsonl"
    for record in records:
        append(path, record)

    raw = path.read_bytes()
    assert raw.count(b"\n") == len(records)
    assert raw.endswith(b"\n")
    lines = path.read_text(encoding="utf-8").split("\n")
    assert lines[-1] == ""
    assert len(lines[:-1]) == len(records)
    # The embedded newline was escaped by the serialiser, not written literally.
    assert b"first line\\nsecond line" in raw
    assert len(read(path)) == len(records)


def test_a_killed_process_leaves_the_record_on_disk(tmp_path: Path) -> None:
    """A real kill after `append` returns, with no chance to flush on exit.

    `os._exit` skips Python's normal shutdown and buffer flush, which is what a
    `kill -9` does. The record is only on disk if `append` flushed it before
    returning, which is the property the ledger's denominators rest on.
    """
    path = tmp_path / "ledger.jsonl"
    script = """
import os
import sys
from pathlib import Path

from precondition_library.bench.ledger import Arm, EpisodeRecord, OccurrenceRole, append
from precondition_library.program import EpisodeOutcome

record = EpisodeRecord(
    arm=Arm.PRECONDITION,
    task_id="sync_fork_with_upstream/seed-1",
    fault_type="diverged",
    occurrence_index=1,
    occurrence_role=OccurrenceRole.VARIANT,
    seed=1,
    tokens_in=10,
    tokens_out=5,
    llm_calls=1,
    wall_clock_s=0.5,
    outcome=EpisodeOutcome.SUCCESS,
    model="test",
    correct_variant="merge",
    ground_truth_ok=True,
)
append(Path(sys.argv[1]), record)
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(path)], cwd=ROOT, check=True)

    assert len(read(path)) == 1
    assert read(path)[0].task_id == "sync_fork_with_upstream/seed-1"


def test_a_torn_tail_is_reported_and_the_records_above_survive(tmp_path: Path) -> None:
    """A crash mid-write leaves a partial line; the complete lines above it stay."""
    path = tmp_path / "ledger.jsonl"
    for seed in (1, 2, 3):
        append(path, _record(seed=seed))

    # Simulate the kill: the bytes of a JSON object cut short, no newline.
    torn = b'{"arm":"precondition","task_id":"sync_fork_with_up'
    with path.open("ab") as handle:
        handle.write(torn)

    with pytest.raises(LedgerCorruptError) as excinfo:
        read(path)
    message = str(excinfo.value)
    assert "line 4" in message
    assert "torn" in message
    assert repr(torn.decode()) in message

    # Remove only the torn tail; the three complete records are still readable.
    complete = path.read_bytes()[: -len(torn)]
    path.write_bytes(complete)
    assert [record.seed for record in read(path)] == [1, 2, 3]


def test_a_malformed_line_in_the_middle_is_not_skipped(tmp_path: Path) -> None:
    """Returning the other records would silently shrink every denominator."""
    path = tmp_path / "ledger.jsonl"
    for seed in (1, 2, 3):
        append(path, _record(seed=seed))

    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, '{"arm":"precondition","unterminated')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerCorruptError) as excinfo:
        read(path)
    assert "line 2" in str(excinfo.value)


def test_a_missing_ledger_is_not_a_corrupt_one(tmp_path: Path) -> None:
    """The dedicated exception lets a caller tell the two apart."""
    with pytest.raises(FileNotFoundError):
        read(tmp_path / "absent.jsonl")


def test_the_line_is_greppable(tmp_path: Path) -> None:
    """`arm` and `fault_type` are flat scalar values, not nested structures."""
    path = tmp_path / "ledger.jsonl"
    append(path, _record(fault_type="diverged"))

    text = path.read_text(encoding="utf-8")
    assert '"arm":"precondition"' in text
    assert '"fault_type":"diverged"' in text


def test_writing_the_ledger_does_not_dirty_the_repository() -> None:
    """The tests must never write into the repository's own tree.

    Asserted as "unchanged since import", not "empty": a contributor running the
    suite on a working branch has uncommitted changes by definition, and that
    says nothing about whether these tests leaked a file.
    """
    assert git_status_porcelain() == GIT_STATUS_AT_IMPORT
