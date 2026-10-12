"""Why arm 3 sits out: the abstention stage names every positive it misses, and the cause.

The stage re-walks the pair pass's pairs, so its first obligation is to agree with that pass:
the same positives, the same negatives and the same arm 3 decisions. The other tests pin each
cause on a library built to produce it, on real sandboxes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.bench.abstentions import (
    CHECKS_REFUSED,
    NO_PROGRAM,
    Abstention,
    abstentions,
    write,
)
from precondition_library.bench.library_pairs import library_pair_outcomes
from precondition_library.library import Library
from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.registry import ambiguous_intents

FAULTS = sorted(intent.fault for intent in ambiguous_intents())
SEED = [2000]
"""The first eval pair seed: one seed is six real environments and 30 pairs."""

NEVER = Predicate(name="never", description="never holds", probe="false")


def _admit(library: Library, program: Program) -> None:
    library.add(program.model_copy(update={"status": ProgramStatus.CANDIDATE}))
    library.set_status(program.id, ProgramStatus.ADMITTED)


def _library(root: Path, programs: list[Program]) -> Library:
    library = Library(root, evaluate_preconditions=evaluate_preconditions)
    for program in programs:
        _admit(library, program)
    return library


def _all_gold() -> list[Program]:
    return [program for intent in ambiguous_intents() for program in gold_programs(intent.name)]


def test_the_stage_agrees_with_the_pair_pass_on_every_count(tmp_path) -> None:
    """Positives, negatives and arm 3's decisions are the pair pass's own, pair for pair."""
    library = _library(tmp_path / "gold", _all_gold())
    before = library.library_hash()
    report = abstentions(library, FAULTS, SEED)
    outcomes = library_pair_outcomes(library, FAULTS, SEED)

    positives = [o for o in outcomes.arm3 if o.correct_variant is not None]
    negatives = [o for o in outcomes.arm3 if o.correct_variant is None]
    assert report.positives == len(positives) and report.negatives == len(negatives)
    assert report.positives + report.negatives == len(outcomes.pairs)
    assert report.arm3_fires == sum(o.fired_variant is not None for o in outcomes.arm3)
    assert report.arm3_fires_on_negatives == sum(o.fired_variant is not None for o in negatives)
    assert len(report.abstentions) == sum(o.fired_variant is None for o in positives)
    assert library.library_hash() == before, "the library is read, never written"


def test_a_state_no_program_resolves_is_no_program(tmp_path) -> None:
    """With nothing admitted for an intent, every one of its positives is `no program`."""
    others = [p for p in _all_gold() if p.provenance.fault != "diverged"]
    report = abstentions(_library(tmp_path / "lib", others), ["diverged"], SEED)

    diverged = [a for a in report.abstentions if a.intent == "sync_fork_with_upstream"]
    assert diverged, "a diverged positive must have been sat out"
    assert all(a.cause == NO_PROGRAM and a.candidates == [] for a in diverged)


def test_a_program_whose_check_fails_is_checks_refused_and_names_the_check(tmp_path) -> None:
    """A program for the right resolution that does not fire is reported with its failed check."""
    blocked = [
        p.model_copy(update={"preconditions": [*p.preconditions, NEVER]})
        for p in gold_programs("sync_fork_with_upstream")
    ]
    report = abstentions(_library(tmp_path / "lib", blocked), ["diverged"], SEED)

    assert report.arm3_fires == 0, "a precondition that never holds blocks every fire"
    assert report.abstentions and all(a.cause == CHECKS_REFUSED for a in report.abstentions)
    for item in report.abstentions:
        acceptable = {*item.acceptable_variants, item.correct_variant}
        assert item.candidates and all(c.variant in acceptable for c in item.candidates)
        assert all("never" in [check.name for check in c.failed] for c in item.candidates)


def test_the_stage_writes_its_rows_and_refuses_a_used_directory(tmp_path) -> None:
    program = Program(
        id="never-fires",
        intent="sync my fork",
        preconditions=[NEVER],
        body="true",
        postconditions=[NEVER],
        variant="rebase",
        provenance=Provenance(
            compiled_from_task="a test",
            model="none",
            compiler_version="0.0.0",
            episode_id="test",
            fault="diverged",
        ),
    )
    report = abstentions(_library(tmp_path / "lib", [program]), ["diverged"], SEED)
    out = tmp_path / "out"
    write(report, out)

    rows = [
        Abstention.model_validate_json(line)
        for line in (out / "abstentions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == len(report.abstentions) > 0
    summary = json.loads((out / "abstentions.json").read_text(encoding="utf-8"))
    assert summary["abstained"] == len(rows)
    assert sum(summary["by_cause"].values()) == len(rows)
    assert "sat out" in (out / "summary.txt").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="fresh directory"):
        write(report, out)
