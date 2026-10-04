"""The live run measures spec §7 item 11's arm-2 floor and reports it beside Figure 1 (#184).

Item 11 registers a gate on the comparison's own baseline: arm 2's strict top-1 on the
informed regime over the tune seeds, against the library the eval dispatches with, must
clear chance by its Wilson lower bound, or a report may not say that precondition
dispatch beats text similarity. The pieces existed (`tune_baseline`,
`arm2_baseline_floor`) but no run called them, so the third live run reported its
difference with no floor beside it. These tests pin:

* the floor is the registered measurement, computed from the library's admitted programs;
* a library that leaves an intent with fewer than two candidate resolutions -- the third
  live run's, which held only `rebase` for `diverged` -- is a verdict, not a crash;
* below the floor, the summary says the Claim-2 wording may not be used.
"""

from __future__ import annotations

from pathlib import Path

from conftest import gold_programs

from precondition_library.bench import live
from precondition_library.bench.report import arm2_baseline_floor
from precondition_library.bench.similarity_probe import program_text_candidates, tune_baseline
from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.similarity import lexical_similarity

INTENTS = ("sync_fork_with_upstream", "restore_submodule_state")


def _library(root: Path, *, keep=lambda program: True) -> Library:
    library = Library(root)
    for intent in INTENTS:
        for program in gold_programs(intent):
            if keep(program):
                library.add(program)
                library.set_status(program.id, ProgramStatus.ADMITTED)
    return library


def test_the_floor_is_the_registered_measurement_on_the_librarys_programs(tmp_path) -> None:
    floor = live.baseline_floor(_library(tmp_path / "lib"))

    candidates = {intent: program_text_candidates(gold_programs(intent)) for intent in INTENTS}
    row = tune_baseline(candidates, lexical_similarity)
    assert floor == arm2_baseline_floor(row.decided, row.decidable)
    assert floor.decidable > 0 and floor.lower_bound is not None


def test_a_candidate_or_demoted_program_is_not_a_candidate_text(tmp_path) -> None:
    """Only admitted programs are dispatched, so only they are arm 2's candidates."""
    library = _library(tmp_path / "lib")
    for program in gold_programs("sync_fork_with_upstream"):
        if program.variant != "rebase":
            library.set_status(program.id, ProgramStatus.DEMOTED)
    assert live.baseline_floor(library).decidable == 0


def test_one_candidate_resolution_is_not_measurable_and_not_usable(tmp_path) -> None:
    """The third live run's library: `diverged` compiled to `rebase` only."""
    library = _library(
        tmp_path / "lib",
        keep=lambda p: p.provenance.fault != "diverged" or p.variant == "rebase",
    )
    floor = live.baseline_floor(library)

    assert floor.usable is False and floor.lower_bound is None
    assert (floor.decided, floor.decidable) == (0, 0)
    assert floor.reason.startswith("not measurable")
    assert "sync_fork_with_upstream has ['rebase']" in floor.reason
    assert "restore_submodule_state" not in floor.reason, "only the short intent is named"


def test_below_the_floor_the_summary_withholds_the_claim_wording() -> None:
    below = arm2_baseline_floor(8, 24)
    assert below.usable is False
    lines = live._floor_lines(below)
    assert lines[0].startswith("arm 2 baseline floor (spec §7 item 11):")
    assert live.NOT_A_WIN_OVER_TEXT in lines[1]

    above = arm2_baseline_floor(20, 24)
    assert above.usable is True
    assert live._floor_lines(above) == [f"arm 2 baseline floor (spec §7 item 11): {above.reason}"]
    assert live._floor_lines(None) == []
