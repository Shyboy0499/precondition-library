"""Dispatching the library on an existing checkout, probing a copy (issue #181, item 4).

`dispatch.dispatch_report` opens a checkout, probes a snapshot of it, and reports which
admitted program arm 3 would fire and each precondition's result. These tests pin:

* **agreement with arm 3**: on every harness state, treated as a checkout -- its
  bindings derived, its upstream pre-fetched and mirrored -- the report fires exactly
  the program `Library.match_preconditions` returns on the same sandbox;
* the original checkout is untouched, even by a probe that writes;
* the text and JSON forms carry the decision and every precondition;
* a linked worktree, and a harness sandbox, are refused by `snapshot`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.__main__ import main
from precondition_library.checkout import NotACheckoutError, open_checkout, snapshot
from precondition_library.dispatch import dispatch_report, render
from precondition_library.library import Library
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import evaluate_preconditions, sandbox_state
from precondition_library.sandbox import run_git
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import ambiguous_intents

INTENTS = sorted(intent.name for intent in ambiguous_intents())
MEASURED = sorted(intent.fault for intent in ambiguous_intents())


def _gold_library(root: Path) -> Library:
    library = Library(root, evaluate_preconditions=evaluate_preconditions)
    for intent in INTENTS:
        for program in gold_programs(intent):
            library.add(program)
            library.set_status(program.id, ProgramStatus.ADMITTED)
    return library


def _first_seed_per_state(fault: str) -> list[int]:
    seeds: dict[str, int] = {}
    for seed in range(200):
        state = FAULTS[fault].variant_for_seed(seed)
        if state is not None:
            seeds.setdefault(state, seed)
    return sorted(seeds.values())


CASES = [([], 0)] + [([f], seed) for f in MEASURED for seed in _first_seed_per_state(f)]


@pytest.mark.parametrize(("faults", "seed"), CASES)
def test_the_checkout_report_fires_what_arm_3_fires_on_the_sandbox(faults, seed, tmp_path) -> None:
    library = _gold_library(tmp_path / "library")
    box = build_sandbox(seed, faults)
    try:
        expected = library.match_preconditions(box)
        before = sandbox_state(box)
        report = dispatch_report(library.root, box.work, scratch=tmp_path)
        assert report.fires == (expected[0].id if expected else None), render(report)
        assert {p.id for p in report.programs if p.accepted} == {p.id for p in expected}
        assert sandbox_state(box) == before, "probing a copy leaves the checkout as it was"
    finally:
        box.destroy()


def _writing_program() -> Program:
    return Program(
        id="writes-in-a-probe",
        intent="sync with upstream",
        variant="merge",
        parameters=[],
        preconditions=[
            Predicate(name="writes", description="touches a file", probe="touch probe-wrote")
        ],
        body="true\n",
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="t",
            model="m",
            compiler_version="v",
            episode_id="e",
            fault="diverged",
        ),
        status=ProgramStatus.CANDIDATE,
    )


def test_a_writing_probe_is_refused_and_never_reaches_the_checkout(tmp_path) -> None:
    library = Library(tmp_path / "library")
    library.add(_writing_program())
    library.set_status("writes-in-a-probe", ProgramStatus.ADMITTED)
    box = build_sandbox(0, [])
    try:
        report = dispatch_report(library.root, box.work, fetch=False, scratch=tmp_path)
        (program,) = report.programs
        assert not program.accepted and program.preconditions[0].refused
        assert report.fires is None
        assert not (box.work / "probe-wrote").exists(), "the write landed in the copy only"
    finally:
        box.destroy()


def test_the_text_and_json_forms_carry_the_decision(tmp_path, capsys) -> None:
    library = _gold_library(tmp_path / "library")
    box = build_sandbox(_first_seed_per_state("diverged")[0], ["diverged"])
    try:
        report = dispatch_report(library.root, box.work, request="sync my fork", scratch=tmp_path)
        text = render(report)
        assert f"would fire: {report.fires}" in text
        assert "request: sync my fork (recorded; preconditions decide)" in text
        for program in report.programs:
            assert program.id in text

        assert (
            main(["dispatch", "--repo", str(box.work), "--library", str(library.root), "--json"])
            == 0
        )
        printed = json.loads(capsys.readouterr().out)
        assert printed["fires"] == report.fires
        assert printed["parameters"]["upstream_remote"] == "upstream"
    finally:
        box.destroy()


def test_snapshot_refuses_a_linked_worktree_and_a_harness_sandbox(tmp_path) -> None:
    box = build_sandbox(0, [])
    try:
        with pytest.raises(ValueError, match="harness sandbox"):
            snapshot(box)
        linked = tmp_path / "linked"
        run_git(("worktree", "add", "-q", "-b", "side", str(linked)), cwd=box.work)
        env = open_checkout(linked, fetch=False, scratch=tmp_path)
        try:
            with pytest.raises(NotACheckoutError, match="linked worktree"):
                snapshot(env)
        finally:
            env.destroy()
    finally:
        box.destroy()
