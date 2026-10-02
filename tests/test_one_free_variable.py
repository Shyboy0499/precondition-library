"""Only the dispatch function varies between arms (issue #4).

#4's last open test item: "tests assert all arms load the same library_hash and that
admission settings are the only free variable." Three facts pin that:

* the dispatch table serves exactly `DISPATCHING_ARMS`, so no arm can silently run
  another arm's matcher;
* in one frozen run every dispatching arm -- 2, 3, 2b and 2c -- reads the same
  unchanged artifact (same hash, same program ids, same gate); and
* two frozen runs that differ only in the gate recorded by the library's build
  produce rows that differ in `admission_gate` and in nothing else the runner
  writes, so the 2x2 factorial's admission factor is not confounded by the harness.

It also pins the constraint #4's first comment raised: `StateFingerprint.observe`
reads `upstream/main`, so every state admission builds must keep it resolvable or it
cannot serve as a negative sandbox (ADR-0018).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeProvider, gold_program, store_programs

from precondition_library.agents.compile import sampled_states
from precondition_library.bench.ledger import Arm, read
from precondition_library.bench.run import DISPATCHING_ARMS, MANIFEST, _dispatch, run_benchmark
from precondition_library.library import Library
from precondition_library.program import Program, ProgramStatus
from precondition_library.sandbox import run_git
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.diverged import SPEC as DIVERGED

DISCARD_SEED = 1  # diverged: empty_local_commits -> discard
_RUN_FIELDS_THAT_MAY_DIFFER = {"wall_clock_s"}


def _discard_for_every_arm() -> Program:
    """The gold `discard` resolution, admitted, keyed to seed 1's request.

    One program every dispatching arm fires on seed 1: arm 3 and 2b on its
    preconditions, arm 2 on similarity (it is the only candidate), and 2c because its
    provenance names the request the episode will send.
    """
    program = gold_program("discard")
    return program.model_copy(
        update={
            "status": ProgramStatus.ADMITTED,
            "provenance": program.provenance.model_copy(
                update={"compiled_from_task": DIVERGED.task_text(DISCARD_SEED)}
            ),
        }
    )


def _frozen_root(path: Path, gate: str) -> Path:
    store_programs(path, [_discard_for_every_arm()])
    (path / MANIFEST).write_text(json.dumps({"admission_gate": gate}), encoding="utf-8")
    return path


def _run(root: Path, out: Path) -> Path:
    return run_benchmark(
        arms=sorted(DISPATCHING_ARMS),
        faults=["diverged"],
        occurrences=1,
        seeds=[DISCARD_SEED],
        out=out,
        model="fake",
        provider=FakeProvider(raises=AssertionError("every arm should replay, not solve")),
        frozen_library=root,
        soft_threshold=1.0,
    )


# --- the dispatch table ---------------------------------------------------------------


def test_the_dispatch_table_serves_exactly_the_dispatching_arms(tmp_path: Path) -> None:
    library = store_programs(tmp_path / "lib", [_discard_for_every_arm()])
    library.soft_threshold = 1.0
    box = build_sandbox(DISCARD_SEED, ["diverged"])
    try:
        signature = TaskSignature(
            intent=DIVERGED.task_text(DISCARD_SEED),
            fingerprint=StateFingerprint.observe(box),
            target=str(box.work),
        )
        for arm in Arm:
            if arm in DISPATCHING_ARMS:
                decision = _dispatch(arm, signature, library, box)
                assert decision.program is not None, f"{arm.value} should fire on seed 1"
            else:
                with pytest.raises(ValueError, match="does not dispatch"):
                    _dispatch(arm, signature, library, box)
    finally:
        box.destroy()


# --- one artifact, every arm ---------------------------------------------------------------


def test_every_dispatching_arm_reads_one_unchanged_library(tmp_path: Path) -> None:
    root = _frozen_root(tmp_path / "frozen", "two_sided")
    before = Library(root).library_hash()

    rows = read(_run(root, tmp_path / "ledger.jsonl"))

    assert {row.arm for row in rows} == DISPATCHING_ARMS
    assert {row.library_hash for row in rows} == {before}
    assert len({tuple(row.library_program_ids or []) for row in rows}) == 1
    assert {row.admission_gate for row in rows} == {"two_sided"}
    assert all(row.fired_variant == "discard" and row.llm_calls == 0 for row in rows)
    assert Library(root).library_hash() == before, "the shared artifact must not move"


def test_admission_is_the_only_free_variable(tmp_path: Path) -> None:
    """Same programs, same arms, same plan: only the recorded gate may differ.

    The two roots hold identical files, so their hash and program ids match too; what a
    real positive-only build changes is *which* programs are admitted, and this test
    shows the runner adds no other difference on top of that.
    """
    gated = _run(_frozen_root(tmp_path / "gated", "two_sided"), tmp_path / "gated.jsonl")
    ungated = _run(_frozen_root(tmp_path / "ungated", "positive_only"), tmp_path / "ungated.jsonl")

    def key(row) -> tuple:
        return (row.arm, row.fault_type, row.seed, row.occurrence_index)

    first = {key(row): row.model_dump() for row in read(gated)}
    second = {key(row): row.model_dump() for row in read(ungated)}
    assert set(first) == set(second), "both runs follow the identical plan"
    for row_key, row in first.items():
        other = second[row_key]
        differing = {
            field
            for field in row
            if row[field] != other[field] and field not in _RUN_FIELDS_THAT_MAY_DIFFER
        }
        assert differing == {"admission_gate"}, (row_key, differing)
        assert (row["admission_gate"], other["admission_gate"]) == ("two_sided", "positive_only")


# --- the observe() constraint ------------------------------------------------------------


@pytest.mark.parametrize("fault,seed", sampled_states(), ids=lambda v: str(v) or "clean")
def test_every_admission_state_keeps_upstream_observable(fault: str, seed: int) -> None:
    """Every state admission builds can be fingerprinted, so it can be a negative."""
    box = build_sandbox(seed, [fault] if fault else [])
    try:
        resolved = run_git(("rev-parse", "--verify", "upstream/main"), cwd=box.work, check=False)
        assert resolved.returncode == 0, f"{fault or 'clean'} at seed {seed} lost upstream/main"
        StateFingerprint.observe(box)
    finally:
        box.destroy()
