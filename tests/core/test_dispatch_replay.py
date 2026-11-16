"""Dry run on a copy, then replay on the checkout only when confirmed (issue #181, last item).

`dispatch.run_dispatch(..., confirm=...)` dry-runs the program that would fire on a
fresh copy of the checkout, shows the caller the report and what the dry run changed,
and replays on the checkout only on `True` -- and only if the checkout has not changed
since it was copied. These tests pin, on harness states treated as checkouts:

* the dry run changes only its copy, and reports what it did there;
* declining leaves the checkout exactly as it was;
* confirming replays on the checkout and fixes it, by the fault's own checker;
* a checkout that changed after it was copied is not replayed on;
* with nothing firing, nothing is dry-run or replayed;
* the command asks before replaying, and `--yes` skips the question.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import gold_programs

from precondition_library.__main__ import main
from precondition_library.dispatch import run_dispatch
from precondition_library.library import Library
from precondition_library.program import ProgramStatus
from precondition_library.runtime.probes import sandbox_state
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import ambiguous_intents


def _gold_library(root: Path) -> Path:
    library = Library(root)
    for intent in ambiguous_intents():
        for program in gold_programs(intent.name):
            library.add(program)
            library.set_status(program.id, ProgramStatus.ADMITTED)
    return root


def _seed(fault: str, state: str) -> int:
    return next(s for s in range(200) if FAULTS[fault].variant_for_seed(s) == state)


@pytest.fixture
def diverged(tmp_path):
    """A diverged state the gold library fires on, as a checkout."""
    box = build_sandbox(_seed("diverged", "merge"), ["diverged"])
    yield box
    box.destroy()


def test_declining_leaves_the_checkout_as_it_was(diverged, tmp_path) -> None:
    library = _gold_library(tmp_path / "library")
    before = sandbox_state(diverged)
    shown = []
    outcome = run_dispatch(
        library,
        diverged.work,
        fetch=False,  # a pre-fetch is a deliberate write; the claim is about the dry run
        scratch=tmp_path,
        confirm=lambda report, dry: shown.append((report, dry)) or False,
    )
    assert outcome.report.fires is not None
    assert outcome.dry_run is not None and outcome.dry_run.ok, outcome.dry_run
    assert outcome.dry_run.program == outcome.report.fires
    assert outcome.dry_run.commits or outcome.dry_run.head_after != outcome.dry_run.head_before
    assert outcome.dry_run.postconditions_held is True
    assert shown and shown[0][1] == outcome.dry_run, "the caller saw the dry run first"
    assert outcome.replayed is None and outcome.not_replayed == "not confirmed"
    assert sandbox_state(diverged) == before, "the dry run changed only its copy"
    assert not FAULTS["diverged"].check(diverged).ok, "still the fault it was"


def test_confirming_replays_on_the_checkout_and_fixes_it(diverged, tmp_path) -> None:
    library = _gold_library(tmp_path / "library")
    outcome = run_dispatch(
        library, diverged.work, scratch=tmp_path, confirm=lambda report, dry: True
    )
    assert outcome.replayed is not None and outcome.replayed.ok, outcome.replayed
    assert FAULTS["diverged"].check(diverged).ok, "the fault's own checker passes"


def test_a_checkout_changed_after_it_was_copied_is_not_replayed_on(diverged, tmp_path) -> None:
    library = _gold_library(tmp_path / "library")

    def change_it_then_confirm(report, dry) -> bool:
        (diverged.work / "edited-meanwhile.txt").write_text("x\n", encoding="utf-8")
        return True

    outcome = run_dispatch(library, diverged.work, scratch=tmp_path, confirm=change_it_then_confirm)
    assert outcome.replayed is None
    assert "changed after it was copied" in (outcome.not_replayed or "")


def test_nothing_fires_so_nothing_is_dry_run_or_replayed(tmp_path) -> None:
    library = _gold_library(tmp_path / "library")
    box = build_sandbox(0, [])
    try:
        outcome = run_dispatch(library, box.work, scratch=tmp_path, confirm=lambda r, d: True)
        assert outcome.report.fires is None
        assert outcome.dry_run is None and outcome.replayed is None
        assert outcome.not_replayed == "no program's preconditions all hold here"
    finally:
        box.destroy()


def test_the_command_asks_before_replaying(diverged, tmp_path, capsys) -> None:
    library = _gold_library(tmp_path / "library")
    before = sandbox_state(diverged)
    argv = [
        "dispatch",
        "--repo",
        str(diverged.work),
        "--library",
        str(library),
        "--replay",
        "--no-fetch",  # compared before and after below, so no deliberate write either
    ]
    asked: list[str] = []

    assert main(argv, answer=lambda prompt: asked.append(prompt) or "n") == 0
    out = capsys.readouterr().out
    assert asked and asked[0].startswith("Replay ")
    assert "dry run of" in out and "not replayed: not confirmed" in out
    assert sandbox_state(diverged) == before

    assert main([*argv, "--yes"], answer=lambda prompt: pytest.fail("--yes must not ask")) == 0
    assert "replayed" in capsys.readouterr().out
    assert FAULTS["diverged"].check(diverged).ok


def test_yes_without_replay_is_refused(diverged, tmp_path) -> None:
    argv = ["dispatch", "--repo", str(diverged.work), "--library", str(tmp_path), "--yes"]
    with pytest.raises(SystemExit, match="--yes only applies with --replay"):
        main(argv)
