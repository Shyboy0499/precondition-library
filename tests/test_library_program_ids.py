"""Every row names the programs its library held (issue #4).

`library_hash` says *whether* two rows saw the same library; `library_program_ids` says
*which* programs that was, so a reader can resolve a digest without the directory. The
list is every program present -- the ones the digest covers -- not only the admitted.
"""

from __future__ import annotations

from pathlib import Path

from conftest import FakeProvider, store_programs
from test_episode_runner import (
    DISCARD_SEED,
    SECOND_DISCARD_SEED,
    _completion,
    _discard_program,
    _reply_text,
    _resolves_discard,
)

from precondition_library.bench.ledger import Arm, OccurrenceRole, read
from precondition_library.bench.run import run_benchmark, run_episode
from precondition_library.library import Library
from precondition_library.program import EpisodeOutcome, ProgramStatus


def test_an_online_row_lists_the_library_as_it_found_it(tmp_path: Path) -> None:
    """The first episode finds nothing; the second finds what the first compiled."""
    out = run_benchmark(
        arms=[Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=2,
        seeds=[DISCARD_SEED, SECOND_DISCARD_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=FakeProvider(*_resolves_discard(), _completion(_reply_text(_discard_program()))),
    )
    first, second = read(out)
    assert first.library_program_ids == []
    assert second.library_program_ids == Library(tmp_path / "library-precondition").program_ids()
    assert len(second.library_program_ids or []) == 1


def test_every_frozen_row_lists_the_same_programs_including_non_admitted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "frozen"
    store_programs(
        root,
        [
            _discard_program(status=ProgramStatus.ADMITTED),
            _discard_program(id="never-admitted", status=ProgramStatus.CANDIDATE),
        ],
    )
    out = run_benchmark(
        arms=[Arm.SEMANTIC, Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=1,
        seeds=[DISCARD_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=FakeProvider(raises=AssertionError("a replay must not call the model")),
        frozen_library=root,
    )
    rows = read(out)
    assert {tuple(row.library_program_ids or []) for row in rows} == {
        ("discard-under-test", "never-admitted")
    }


def test_an_invalid_row_still_names_its_library(tmp_path: Path, monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated sandbox failure")

    monkeypatch.setattr("precondition_library.bench.run.build_sandbox", _boom)
    root = tmp_path / "lib"
    store_programs(root, [_discard_program(status=ProgramStatus.ADMITTED)])

    record = run_episode(
        Arm.PRECONDITION,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(),
        library=Library(root),
        model="fake",
    )
    assert record.outcome is EpisodeOutcome.INVALID
    assert record.library_program_ids == ["discard-under-test"]
