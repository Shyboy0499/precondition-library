"""What a fired program does when it is replayed, graded as an episode is (exploratory stage).

`bench.consequences` replays each dispatch arm's fires on a fresh build of the pair's state.
These tests pin its grader on real sandboxes, one case per outcome, so a figure read from it
names what happened to the repository:

* a fault's correct resolution is `fixed`;
* a wrong one that leaves the fault in place is `not fixed`, with the checker's reason;
* a body that destroys a recorded commit's object is `lost recorded state`;
* on a fault-free state, a no-op is `unchanged` and anything that moves is `changed`;
* a body the guard refuses, or one naming a parameter the state cannot bind, is `nothing ran`;
* a checker that raises is `ungradable`, not a crash of the stage;
* the committed results are Figure 1's decisions, and their summaries are their rows.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from conftest import gold_program

from precondition_library.bench.consequences import (
    CHANGED,
    FIXED,
    LOST,
    NOT_FIXED,
    NOTHING_RAN,
    UNCHANGED,
    UNGRADABLE,
    Consequence,
    ConsequenceSummary,
    consequence_of,
)
from precondition_library.bench.library_pairs import FAULT_FREE
from precondition_library.program import Program, ProgramStatus, Provenance
from precondition_library.tasks.faults import FAULTS

MERGE_SEED = 0
"""`diverged` injects its `merge` state at seed 0."""


def _program(body: str, *, parameters: list[str] | None = None) -> Program:
    return Program(
        id="under-test",
        intent="t",
        variant="v",
        parameters=parameters or [],
        preconditions=[],
        body=body,
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="t", model="m", compiler_version="v", episode_id="e", fault="x"
        ),
        status=ProgramStatus.ADMITTED,
    )


def test_a_correct_resolution_is_fixed() -> None:
    assert FAULTS["diverged"].variant_for_seed(MERGE_SEED) == "merge"
    outcome, ok, _ = consequence_of(gold_program("merge"), MERGE_SEED, "diverged")
    assert (outcome, ok) == (FIXED, True)


def test_discarding_local_commits_is_not_fixed_with_the_checkers_reason() -> None:
    outcome, ok, detail = consequence_of(
        _program("git reset -q --hard upstream/main\n"), MERGE_SEED, "diverged"
    )
    assert (outcome, ok) == (NOT_FIXED, True)
    assert detail


def test_destroying_a_recorded_commit_is_lost_state() -> None:
    body = (
        "git reset -q --hard upstream/main\n"
        "git reflog expire --expire=now --all\n"
        "git gc -q --prune=now\n"
    )
    outcome, _, detail = consequence_of(_program(body), MERGE_SEED, "diverged")
    assert outcome == LOST, detail
    assert "no longer in the repository" in detail


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("true\n", UNCHANGED),
        ("git commit -q --allow-empty -m 'nothing needed doing'\n", CHANGED),
        ("echo scratch > notes.txt\n", CHANGED),
    ],
)
def test_on_a_fault_free_state_anything_that_moves_is_changed(body: str, expected: str) -> None:
    outcome, _, _ = consequence_of(_program(body), 0, FAULT_FREE)
    assert outcome == expected


@pytest.mark.parametrize(
    ("program", "reason"),
    [
        (_program("curl -s https://example.com\n"), "refused"),
        (
            _program("git -C {submodule_path} status\n", parameters=["submodule_path"]),
            "cannot bind",
        ),
    ],
)
def test_a_body_that_never_ran_is_nothing_ran(program: Program, reason: str) -> None:
    outcome, ok, detail = consequence_of(program, 0, FAULT_FREE)
    assert (outcome, ok) == (NOTHING_RAN, False)
    assert reason in detail, detail


def test_a_checker_that_raises_is_ungradable(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(sandbox):
        raise RuntimeError("the checker could not read the state")

    monkeypatch.setattr(FAULTS["diverged"], "check", raises)
    outcome, _, detail = consequence_of(gold_program("merge"), MERGE_SEED, "diverged")
    assert outcome == UNGRADABLE
    assert "could not read the state" in detail


RESULTS = Path(__file__).resolve().parents[1] / "results"


@pytest.mark.parametrize("run", ["run-11", "run-12", "run-13"])
def test_the_committed_replays_are_figure_1s_decisions(run: str) -> None:
    """Each run's arm-2 threshold and its fires and wrong fires there are the committed primary
    report's, arm 3's fires are its 187-189, and the summary is the rows on disk."""
    out = RESULTS / "consequences-2026-10-21" / run
    summary = ConsequenceSummary.model_validate_json((out / "summary.json").read_text("utf-8"))
    rows = [
        Consequence.model_validate_json(line)
        for line in (out / "consequences.jsonl").read_text("utf-8").splitlines()
    ]
    primary = (RESULTS / "replicates-2026-10-05" / run / "primary" / "primary.txt").read_text(
        "utf-8"
    )
    matched = re.search(r"arm 2 \(threshold ([0-9.]+)\) has mismatch (\d+)/(\d+)", primary)
    assert matched is not None
    assert summary.arm2_threshold == float(matched.group(1))
    arm2 = [row for row in rows if row.arm == "arm2"]
    assert sum(not row.correct for row in arm2) == int(matched.group(2))
    assert len(arm2) == int(matched.group(3))
    arm3 = [row for row in rows if row.arm == "arm3"]
    assert all(row.correct for row in arm3)
    assert len(arm3) == {"run-11": 187, "run-12": 187, "run-13": 189}[run]

    recounted: dict[str, Counter[str]] = {}
    for row in rows:
        key = f"{row.arm}/{'correct' if row.correct else 'wrong'}"
        recounted.setdefault(key, Counter())[row.outcome] += 1
    assert summary.counts == {key: dict(value) for key, value in recounted.items()}
    assert not any(row.outcome in (LOST, CHANGED) for row in rows), "nothing was destroyed"


@pytest.mark.parametrize("real_hosts", [False, True])
def test_real_hosts_scope_every_build_to_the_pinned_histories(
    real_hosts: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The arms' decisions and the replays are both built inside `_run`, so the resolver must be
    active for the whole of it, and only when asked for."""
    from precondition_library import sandbox
    from precondition_library.bench import consequences
    from precondition_library.bench.realhost import REAL_HOSTS

    seen: list[object] = []

    def capture(*args, **kwargs):
        resolver = sandbox._REAL_HOST_FOR_SEED.get()
        seen.append(None if resolver is None else resolver(2000))
        return "measured"

    monkeypatch.setattr(consequences, "_run", capture)
    assert (
        consequences.run_consequences(tmp_path / "run", tmp_path / "out", real_hosts=real_hosts)
        == "measured"
    )
    assert seen == [REAL_HOSTS[0] if real_hosts else None]
    assert sandbox._REAL_HOST_FOR_SEED.get() is None, "the scope ends with the stage"


def _rows(directory: Path) -> list[Consequence]:
    return [
        Consequence.model_validate_json(line)
        for line in (directory / "consequences.jsonl").read_text("utf-8").splitlines()
    ]


def _held_out_block(fault: str, run: str) -> Path:
    """Where each committed held-out block of the held-out stage lives (parts 1-4)."""
    if fault == "dirty_tree":
        part = "heldout-2026-10-10" if run == "run-12" else "heldout-2026-10-16/dirty_tree"
        return RESULTS / part / run / "summary.json"
    part = {
        "diverged": "heldout-2026-10-16",
        "lockfile_conflict": "heldout-2026-10-18",
        "branch_renamed": "heldout-2026-10-19",
        "submodule_moved": "heldout-2026-10-19",
    }[fault]
    return RESULTS / part / fault / run / "summary.json"


@pytest.mark.parametrize("run", ["run-11", "run-12", "run-13"])
def test_the_held_out_replays_are_the_held_out_stages_choices(run: str) -> None:
    """Arm 3's fires and wrong fires per fault are the committed held-out blocks', the
    summary is the rows, and no fire on a fault-free state changed anything."""
    from precondition_library.bench.heldout import HELD_OUT_FAULTS, HeldOutSummary

    out = RESULTS / "consequences-heldout-2026-10-21" / run
    rows = _rows(out)
    summary = ConsequenceSummary.model_validate_json((out / "summary.json").read_text("utf-8"))
    assert summary.seeds == list(range(3000, 3040)) and summary.base == "synthetic"
    for fault in HELD_OUT_FAULTS:
        block = HeldOutSummary.model_validate_json(_held_out_block(fault, run).read_text("utf-8"))
        mine = [row for row in rows if row.arm == "arm3" and row.environment == fault]
        assert len(mine) == block.arm3_fires, fault
        assert sum(not row.correct for row in mine) == block.arm3_wrong, fault
    assert not any(row.outcome == CHANGED for row in rows)


@pytest.mark.parametrize("run", ["run-11", "run-12", "run-13"])
def test_the_real_host_replays_agree_with_the_synthetic_ones_row_for_row(run: str) -> None:
    """Over the pinned real histories every fire has the synthetic base's outcome (ADR-0045)."""

    def key(row: Consequence) -> tuple:
        return (row.arm, row.seed, row.environment, row.program_id, row.correct, row.outcome)

    real_out = RESULTS / "consequences-realhost-2026-10-21" / run
    summary = ConsequenceSummary.model_validate_json((real_out / "summary.json").read_text("utf-8"))
    assert summary.base == "real-host"
    real = _rows(real_out)
    synthetic = _rows(RESULTS / "consequences-2026-10-21" / run)
    assert [key(row) for row in real] == [key(row) for row in synthetic]
