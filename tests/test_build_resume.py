"""An interrupted build resumes from the episodes it committed.

The fifth and ninth live runs lost their builds to a container restart part-way through,
and a build is the expensive half of a run. These tests pin that a resumed build skips
every committed episode, re-reads its programs, removes what an interrupted episode had
copied, and ends with what one uninterrupted build would have made; and that a live run
resumes only its own plan, and only while it was still building.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeProvider
from test_admit_set import _FinishThenNoProgram
from test_episode_runner import (
    DISCARD_SEED,
    _completion,
    _discard_program,
    _reply_text,
    _resolves_discard,
)
from test_live_run import PLAN, stubbed  # noqa: F401 -- the fixture is used by name

from precondition_library.bench import live
from precondition_library.bench.admit_set import ADMIT_SET, admit_request
from precondition_library.bench.build_library import build_library, progress_path
from precondition_library.bench.ledger import read
from precondition_library.library import Library


class _InterruptedAfter(_FinishThenNoProgram):
    """Solves `solves` episodes, then is interrupted as a restart would interrupt it."""

    def __init__(self, solves: int) -> None:
        super().__init__()
        self._solves = solves

    def complete(self, *, system: str, messages: list[dict], tools: list[dict] | None = None):
        if tools and len(self.requests) == self._solves:
            raise KeyboardInterrupt
        return super().complete(system=system, messages=messages, tools=tools)


def _build(tmp_path: Path, provider, **kwargs):
    return build_library(
        faults=["diverged"],
        root=tmp_path / "library",
        ledger=tmp_path / "build.jsonl",
        provider=provider,
        model="fake",
        positive_only_root=tmp_path / "ungated",
        **kwargs,
    )


def test_a_resumed_build_runs_only_the_episodes_left(tmp_path: Path) -> None:
    requests = [admit_request("diverged", e, s) for e in ADMIT_SET["diverged"] for s in e.seeds]
    with pytest.raises(KeyboardInterrupt):
        _build(tmp_path, _InterruptedAfter(2))
    assert len(progress_path(tmp_path / "build.jsonl").read_text().splitlines()) == 2

    provider = _FinishThenNoProgram()
    report = _build(tmp_path, provider, resume=True)

    assert provider.requests == requests[2:], "the two committed episodes are not run again"
    rows = read(tmp_path / "build.jsonl")
    assert [row.seed for row in rows] == [s for e in ADMIT_SET["diverged"] for s in e.seeds]
    assert report.programs == []


def test_a_resumed_build_keeps_its_programs_and_drops_an_interrupted_copy(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(*_resolves_discard(), _completion(_reply_text(_discard_program())))
    first = _build(tmp_path, provider, seeds=(DISCARD_SEED,))
    assert first.admitted == 1
    orphan = tmp_path / "library" / "diverged-occ2-cut-off"
    orphan.mkdir()
    (orphan / "program.yaml").write_text("id: half-written\n", encoding="utf-8")

    unused = FakeProvider()
    resumed = _build(tmp_path, unused, seeds=(DISCARD_SEED,), resume=True)

    assert unused.calls == [], "every episode was committed"
    assert not orphan.exists(), "what an interrupted episode copied is removed"
    assert resumed.programs == first.programs
    assert resumed.positive_only is not None and first.positive_only is not None
    assert resumed.positive_only.programs == first.positive_only.programs
    assert resumed.library_hash == first.library_hash
    assert [p.id for p in Library(tmp_path / "library").load_all()] == [
        p.program_id for p in first.programs
    ]


def test_a_resumed_build_refuses_to_delete_what_it_did_not_write(tmp_path: Path) -> None:
    _build(tmp_path, _FinishThenNoProgram(), seeds=(0,))
    stranger = tmp_path / "library" / "notes"
    stranger.mkdir()
    (stranger / "todo.txt").write_text("mine\n", encoding="utf-8")
    with pytest.raises(ValueError, match="removes only the program directories it wrote"):
        _build(tmp_path, _FinishThenNoProgram(), seeds=(0,), resume=True)
    assert (stranger / "todo.txt").exists()


def test_a_fresh_build_refuses_an_earlier_builds_progress(tmp_path: Path) -> None:
    _build(tmp_path, _FinishThenNoProgram(), seeds=(0,))
    with pytest.raises(ValueError, match="pass resume=True"):
        build_library(
            faults=["diverged"],
            root=tmp_path / "other",
            ledger=tmp_path / "build.jsonl",
            provider=_FinishThenNoProgram(),
            model="fake",
            seeds=(0,),
        )


# --- a live run --------------------------------------------------------------------


def _interrupted_run(out: Path, monkeypatch) -> None:
    def restart(**_kwargs):
        raise KeyboardInterrupt

    real = live.build_library
    monkeypatch.setattr(live, "build_library", restart)
    with pytest.raises(KeyboardInterrupt):
        live.run_live(PLAN, provider=object(), model="fake", out=out)
    monkeypatch.setattr(live, "build_library", real)


def test_a_live_run_interrupted_in_its_build_resumes_and_finishes(
    stubbed,  # noqa: F811
    tmp_path,
    monkeypatch,
) -> None:
    out = tmp_path / "run"
    _interrupted_run(out, monkeypatch)
    result = live.run_live(PLAN, provider=object(), model="fake", out=out, resume=True)
    assert stubbed["build"][-1]["resume"] is True
    assert result.figure1 is not None
    assert (out / "summary.json").exists()
    with pytest.raises(ValueError, match="already finished"):
        live.run_live(PLAN, provider=object(), model="fake", out=out, resume=True)


def test_a_live_run_resumes_only_its_own_plan(stubbed, tmp_path, monkeypatch) -> None:  # noqa: F811
    out = tmp_path / "run"
    _interrupted_run(out, monkeypatch)
    with pytest.raises(ValueError, match="different plan or model"):
        live.run_live(PLAN, provider=object(), model="other", out=out, resume=True)
    other = PLAN.model_copy(update={"episodes": not PLAN.episodes})
    with pytest.raises(ValueError, match="different plan or model"):
        live.run_live(other, provider=object(), model="fake", out=out, resume=True)


def test_a_live_run_past_its_build_does_not_resume(stubbed, tmp_path, monkeypatch) -> None:  # noqa: F811
    out = tmp_path / "run"
    _interrupted_run(out, monkeypatch)
    (out / "primary").mkdir()
    with pytest.raises(ValueError, match="got past its build"):
        live.run_live(PLAN, provider=object(), model="fake", out=out, resume=True)


def test_nothing_to_resume_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="no interrupted run"):
        live.run_live(PLAN, provider=object(), model="fake", out=tmp_path / "none", resume=True)


def test_the_plan_is_recorded_first(tmp_path, monkeypatch) -> None:
    out = tmp_path / "run"
    _interrupted_run(out, monkeypatch)
    recorded = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert recorded == {"model": "fake", "plan": PLAN.model_dump(mode="json")}


def test_the_command_passes_resume(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("k", encoding="utf-8")
    seen: dict = {}

    def capture(plan, **kwargs):
        seen.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(live, "run_live", capture)
    with pytest.raises(SystemExit):
        live.main(["--api-key-file", str(key_file), "--out", str(tmp_path / "o"), "--resume"])
    assert seen["resume"] is True
