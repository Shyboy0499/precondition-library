"""One frozen library, built once from the admit set, dispatched against by every arm.

Issue #4 and ADR-0009. Two halves are pinned here with a scripted provider, never a live
model:

* `build_library` solves, compiles and gates each admit-set seed against its own empty
  scratch library, so nothing is dispatched while the artifact is built, and copies
  every program it produced -- admitted or not -- into one root.
* `run_benchmark(frozen_library=...)` dispatches every arm against that root and never
  writes to it: no compile on fallback, no demotion, no quarantine. Every row carries
  the same `library_hash`, and a misfire is still recorded on the row.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider
from test_episode_runner import (
    DISCARD_SEED,
    REPLAY_SEED,
    VARIANT_SEED,
    _completion,
    _discard_program,
    _finish,
    _fires_on_any_local_work,
    _library_with_admitted,
    _reply_text,
    _resolves_discard,
)

from precondition_library.bench.build_library import build_library
from precondition_library.bench.ledger import Arm, read
from precondition_library.bench.run import run_benchmark
from precondition_library.library import Library
from precondition_library.program import ProgramStatus

# --- building -----------------------------------------------------------------


def test_the_build_compiles_and_gates_each_seed_into_one_root(tmp_path: Path) -> None:
    """One seed, solved and compiled: its admitted program lands in the frozen root."""
    provider = FakeProvider(*_resolves_discard(), _completion(_reply_text(_discard_program())))
    report = build_library(
        faults=["diverged"],
        root=tmp_path / "frozen",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        seeds=(DISCARD_SEED,),
    )

    assert report.admitted == 1
    (built,) = report.programs
    assert (built.fault, built.seed, built.admitted) == ("diverged", DISCARD_SEED, True)
    programs = Library(tmp_path / "frozen").load_all()
    assert [(p.id, p.status) for p in programs] == [(built.program_id, ProgramStatus.ADMITTED)]
    assert (tmp_path / "frozen" / built.program_id / "history.jsonl").exists(), (
        "the admission's history travels with the program"
    )
    assert report.library_hash == Library(tmp_path / "frozen").library_hash()
    (row,) = read(tmp_path / "build.jsonl")
    assert row.llm_calls == 4, "three solve turns and one compile: the build's cost is recorded"


def test_the_build_refuses_a_directory_that_already_holds_programs(tmp_path: Path) -> None:
    """Built once into an empty directory, so the contents are exactly this build's."""
    _library_with_admitted(tmp_path / "frozen", _discard_program())
    with pytest.raises(ValueError, match="already holds 1 program"):
        build_library(
            faults=["diverged"],
            root=tmp_path / "frozen",
            ledger=tmp_path / "build.jsonl",
            provider=FakeProvider(),
            model="fake",
            seeds=(DISCARD_SEED,),
        )


def test_the_build_accepts_a_directory_with_only_documentation(tmp_path: Path) -> None:
    """`library/` carries a README; that is not a program, so it can be the root."""
    root = tmp_path / "library"
    root.mkdir()
    (root / "README.md").write_text("# The program library\n", encoding="utf-8")
    provider = FakeProvider(*_resolves_discard(), _completion(_reply_text(_discard_program())))
    report = build_library(
        faults=["diverged"],
        root=root,
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        seeds=(DISCARD_SEED,),
    )
    assert report.admitted == 1
    assert (root / "README.md").read_text(encoding="utf-8") == "# The program library\n"


# --- dispatching against it -----------------------------------------------------


def test_every_arm_dispatches_against_the_same_unchanged_library(tmp_path: Path) -> None:
    """Both dispatch arms replay from one artifact, and every row names the same hash."""
    root = tmp_path / "frozen"
    _library_with_admitted(root, _discard_program())
    before = Library(root).library_hash()

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
    assert [row.arm for row in rows] == [Arm.SEMANTIC, Arm.PRECONDITION]
    assert {row.library_hash for row in rows} == {before}
    assert all(row.fired_variant == "discard" for row in rows)
    assert Library(root).library_hash() == before
    assert not (tmp_path / "library-semantic").exists(), "no per-arm library is grown"


def test_a_frozen_library_counts_misfires_on_the_row_but_never_quarantines(
    tmp_path: Path,
) -> None:
    """Online, two wrong fires quarantine a program; frozen, the artifact stays put.

    The wrong fire is `discard` on a `merge` state (ADR-0023: merge and rebase are
    acceptable on every diverged state, so only discard on real local work misfires).
    """
    root = tmp_path / "frozen"
    wrong = _fires_on_any_local_work(id="always-wrong-variant")
    _library_with_admitted(root, wrong)
    before = Library(root).library_hash()

    out = run_benchmark(
        arms=[Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=2,
        seeds=[VARIANT_SEED, REPLAY_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=FakeProvider(raises=AssertionError("a replay must not call the model")),
        frozen_library=root,
    )

    rows = read(out)
    assert [row.misfired for row in rows] == [True, True]
    assert [p.status for p in Library(root).load_all()] == [ProgramStatus.ADMITTED]
    assert Library(root).mismatch_count(wrong.id) == 0
    assert Library(root).library_hash() == before


def test_a_frozen_fallback_is_solved_but_never_compiled(tmp_path: Path) -> None:
    """No program applies to the merge state; the agent solves and nothing is stored.

    The provider holds only the solve's single turn. Online, the runner would then
    ask it for a compile; frozen, it must not, so the call count stays at one and the
    row carries no compile outcome.
    """
    root = tmp_path / "frozen"
    _library_with_admitted(root, _discard_program())
    provider = FakeProvider(_finish())

    out = run_benchmark(
        arms=[Arm.PRECONDITION],
        faults=["diverged"],
        occurrences=1,
        seeds=[VARIANT_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=provider,
        frozen_library=root,
    )

    (row,) = read(out)
    assert row.fired_variant is None
    assert len(provider.calls) == 1, "the solve ran; no compile was requested"
    assert row.compile_failure_reason is None and row.admitted is None
    assert [p.id for p in Library(root).load_all()] == ["discard-under-test"]


def test_a_frozen_run_refuses_a_library_with_nothing_to_dispatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no admitted program"):
        run_benchmark(
            arms=[Arm.PRECONDITION],
            faults=["diverged"],
            occurrences=1,
            seeds=[DISCARD_SEED],
            out=tmp_path / "ledger.jsonl",
            model="fake",
            provider=FakeProvider(),
            frozen_library=tmp_path / "absent",
        )
