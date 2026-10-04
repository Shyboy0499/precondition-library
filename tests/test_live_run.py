"""The committed live-run driver wires the repository's own stages together (#163).

The first live run went through a driver outside the repository. `bench.live` is that
driver, committed. A live model cannot run here, so the stages that call one -- the build
and the episode runs -- are replaced by stand-ins that record how they were called. The
stages that need no model -- the 2b tuning, Figure 1 and the summary -- run for real on a
library of admitted gold programs. The key-file handling is tested on its own: the key is
read from a file, and nothing prints it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import gold_programs, make_record

from precondition_library.agents.compile import AdmissionGate
from precondition_library.bench import live
from precondition_library.bench import run as run_module
from precondition_library.bench.build_library import (
    BuildReport,
    BuiltProgram,
    _write_manifest,
)
from precondition_library.bench.ledger import Arm, EpisodeOutcome, append, read
from precondition_library.library import Library
from precondition_library.program import ProgramStatus

PLAN = live.LivePlan(
    build_seeds=(0,), tune_seeds=(0, 1), pair_seeds=(0, 1), episode_seeds=(2000, 2001)
)


def _fill(root: Path, gate: AdmissionGate) -> list[BuiltProgram]:
    """Stand in for one gated build: every gold program, admitted, plus the manifest."""
    library = Library(root)
    built = []
    for intent in ("sync_fork_with_upstream", "restore_submodule_state"):
        for program in gold_programs(intent):
            library.add(program)
            library.set_status(program.id, ProgramStatus.ADMITTED)
            built.append(
                BuiltProgram(
                    fault=program.provenance.fault, seed=0, program_id=program.id, admitted=True
                )
            )
    _write_manifest(root, gate, list(live.MEASURED_FAULTS), (0,))
    return built


REJECTED = "negative side failed: preconditions accepted an overlap state"


def _write_build_rows(ledger: Path, *, admitted: bool) -> None:
    """The two kinds of build row the second live run produced (#173)."""
    append(
        ledger,
        make_record(
            arm=Arm.PRECONDITION,
            outcome=EpisodeOutcome.FALLBACK,
            seed=0,
            tool_calls=15,
            admitted=admitted,
            compile_failure_reason=None if admitted else REJECTED,
        ),
    )
    append(
        ledger,
        make_record(
            arm=Arm.PRECONDITION,
            outcome=EpisodeOutcome.FAIL,
            fault_type="submodule_moved",
            seed=1,
            tool_calls=24,
            admitted=None,
        ),
    )


@pytest.fixture
def stubbed(monkeypatch):
    calls: dict[str, list] = {"build": [], "benchmark": [], "report": [], "admit": [True]}

    def fake_build(**kwargs) -> BuildReport:
        calls["build"].append(kwargs)
        root, ungated = kwargs["root"], kwargs["positive_only_root"]
        admit = calls["admit"][0]
        _write_build_rows(kwargs["ledger"], admitted=admit)
        if not admit:
            for target, gate in (
                (root, AdmissionGate.TWO_SIDED),
                (ungated, AdmissionGate.POSITIVE_ONLY),
            ):
                target.mkdir(parents=True)
                _write_manifest(target, gate, list(live.MEASURED_FAULTS), (0,))
            empty = dict(
                ledger=kwargs["ledger"], programs=[], library_hash=Library(root).library_hash()
            )
            return BuildReport(
                root=root,
                gate=AdmissionGate.TWO_SIDED,
                positive_only=BuildReport(root=ungated, gate=AdmissionGate.POSITIVE_ONLY, **empty),
                **empty,
            )
        built = _fill(root, AdmissionGate.TWO_SIDED)
        _fill(ungated, AdmissionGate.POSITIVE_ONLY)
        second = BuildReport(
            root=ungated,
            ledger=kwargs["ledger"],
            gate=AdmissionGate.POSITIVE_ONLY,
            programs=built,
            library_hash=Library(ungated).library_hash(),
        )
        return BuildReport(
            root=root,
            ledger=kwargs["ledger"],
            gate=AdmissionGate.TWO_SIDED,
            programs=built,
            library_hash=Library(root).library_hash(),
            positive_only=second,
        )

    def fake_benchmark(**kwargs) -> Path:
        calls["benchmark"].append(kwargs)
        out: Path = kwargs["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("", encoding="utf-8")
        # One row per call, tagged with its replicate, so a concatenation is checkable.
        append(out, make_record(arm=Arm.REACT, replicate=kwargs.get("replicate", 1)))
        return out

    monkeypatch.setattr(live, "build_library", fake_build)
    monkeypatch.setattr(live, "run_benchmark", fake_benchmark)
    monkeypatch.setattr(run_module, "run_benchmark", fake_benchmark)
    monkeypatch.setattr(live, "write_report", lambda ledger, dest: calls["report"].append(ledger))
    return calls


def test_the_stages_run_in_order_against_the_right_libraries(stubbed, tmp_path) -> None:
    out = tmp_path / "run"
    result = live.run_live(PLAN, provider=object(), model="fake", out=out)

    (build,) = stubbed["build"]
    assert build["seeds"] == PLAN.build_seeds and build["root"] == out / "library-two-sided"

    frozen, ungated, online = stubbed["benchmark"]
    assert frozen["arms"] == list(live.FROZEN_ARMS)
    assert frozen["frozen_library"] == out / "library-two-sided"
    assert frozen["soft_threshold"] == result.soft_threshold, "2b runs at the learned floor"
    assert ungated["arms"] == [Arm.SEMANTIC, Arm.PRECONDITION]
    assert ungated["frozen_library"] == out / "library-positive-only"
    assert online["arms"] == [Arm.REACT, Arm.REACT_MEMORY]
    assert "frozen_library" not in online, "arm 1b learns, so it runs online only"
    for call in stubbed["benchmark"]:
        assert call["seeds"] == list(PLAN.episode_seeds)

    assert stubbed["report"] == [out / "frozen.jsonl"], "the main report reads one library"
    assert (out / "factorial.jsonl").exists()


def test_figure1_and_the_summary_are_written_from_the_library(stubbed, tmp_path) -> None:
    out = tmp_path / "run"
    result = live.run_live(PLAN, provider=object(), model="fake", out=out)

    assert (out / "primary" / "figure1.csv").exists()
    assert "NO COMPARISON" in result.figure1 and "labelling rule" in result.figure1, (
        "gold arm 3 is the labelling rule, and the summary says so instead of comparing"
    )
    assert result.admitted_two_sided == result.compiled
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written["soft_threshold"] == result.soft_threshold
    assert result.arm2_floor is not None and written["arm2_floor"]["decidable"] > 0, (
        "item 11's floor is measured on the library before any eval episode (#184)"
    )
    assert "arm 2 baseline floor" in (out / "summary.txt").read_text(encoding="utf-8")
    assert (out / "summary.txt").read_text(encoding="utf-8").startswith("model: fake")


def test_a_run_refuses_an_existing_directory_and_can_skip_online(stubbed, tmp_path) -> None:
    (tmp_path / "used").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        live.run_live(PLAN, provider=object(), model="fake", out=tmp_path / "used")

    plan = PLAN.model_copy(update={"online": False})
    result = live.run_live(plan, provider=object(), model="fake", out=tmp_path / "fresh")
    assert len(stubbed["benchmark"]) == 2
    assert "online_ledger" not in result.artifacts


def test_the_key_comes_from_a_file_and_is_never_printed(monkeypatch, tmp_path, capsys) -> None:
    secret = "sk-test-not-a-real-key"
    key_file = tmp_path / "key"
    key_file.write_text(f"  {secret}\n", encoding="utf-8")
    assert live.read_api_key(key_file) == secret

    seen: dict = {}

    def fake_run(plan, *, provider, model, out):
        seen.update(plan=plan, provider=provider, model=model)
        return live.LiveSummary(
            model=model,
            plan=plan,
            admitted_two_sided=0,
            admitted_positive_only=0,
            compiled=0,
            library_hash="h",
            build=[],
            soft_threshold=1.0,
            claim2="c",
            claim2_reason="r",
            figure1="f",
            factorial=[],
            artifacts={},
        )

    monkeypatch.setattr(live, "run_live", fake_run)
    argv = ["--api-key-file", str(key_file), "--out", str(tmp_path / "o")]
    assert live.main([*argv, "--episode-seeds", "2", "--skip-online"]) == 0
    assert seen["plan"].episode_seeds == (2000, 2001) and seen["plan"].online is False
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize("content", [None, "  \n"])
def test_a_missing_or_empty_key_file_is_refused_without_echoing(tmp_path, content) -> None:
    key_file = tmp_path / "key"
    if content is not None:
        key_file.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit, match="key file"):
        live.read_api_key(key_file)


def test_the_episode_seed_count_is_bounded(tmp_path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("k", encoding="utf-8")
    for bad in ("0", "41"):
        with pytest.raises(SystemExit):
            live.main(
                [
                    "--api-key-file",
                    str(key_file),
                    "--out",
                    str(tmp_path / "o"),
                    "--episode-seeds",
                    bad,
                ]
            )


def test_the_key_can_come_from_a_named_environment_variable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LIVE_TEST_KEY", " sk-env ")
    assert live.read_api_key_env("LIVE_TEST_KEY") == "sk-env"
    monkeypatch.setenv("LIVE_TEST_KEY", "")
    with pytest.raises(SystemExit, match="LIVE_TEST_KEY"):
        live.read_api_key_env("LIVE_TEST_KEY")


def test_exactly_one_key_source_is_required(tmp_path) -> None:
    out = ["--out", str(tmp_path / "o")]
    with pytest.raises(SystemExit):
        live.main(out)
    with pytest.raises(SystemExit):
        live.main([*out, "--api-key-env", "X", "--api-key-file", str(tmp_path / "k")])


def test_every_summary_reports_each_build_episode(stubbed, tmp_path) -> None:
    result = live.run_live(PLAN, provider=object(), model="fake", out=tmp_path / "run")

    admitted, never_done = result.build
    assert (admitted.seed, admitted.admitted, admitted.reason) == (0, True, None)
    assert never_done.admitted is None and never_done.tool_calls == 24
    assert never_done.reason == "not compiled: the agent did not declare the task done"
    assert result.stopped_after is None


def test_an_empty_library_stops_cleanly_after_the_build(stubbed, tmp_path) -> None:
    """The second live run's case (#173): nothing admitted, so stages 2-4 are skipped."""
    stubbed["admit"][0] = False
    out = tmp_path / "run"
    result = live.run_live(PLAN, provider=object(), model="fake", out=out)

    assert result.stopped_after == "build"
    assert "admitted none" in (result.stop_reason or "")
    assert result.build[0].reason == REJECTED, "the gate's reason reaches the summary"
    (online,) = stubbed["benchmark"]
    assert online["arms"] == [Arm.REACT, Arm.REACT_MEMORY], "the online arms need no library"
    assert stubbed["report"] == [] and not (out / "primary").exists()
    assert result.soft_threshold is None and result.figure1 is None
    assert result.arm2_floor is None, "no library, so no floor to measure"

    text = (out / "summary.txt").read_text(encoding="utf-8")
    assert "STOPPED after build" in text and REJECTED in text
    assert (
        json.loads((out / "summary.json").read_text(encoding="utf-8"))["stopped_after"] == "build"
    )


def test_the_command_exits_1_with_a_message_when_it_stopped(monkeypatch, tmp_path, capsys) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("k", encoding="utf-8")
    stopped = live.LiveSummary(
        model="m",
        plan=PLAN,
        admitted_two_sided=0,
        admitted_positive_only=0,
        compiled=0,
        library_hash="h",
        build=[],
        stopped_after="build",
        stop_reason="nothing admitted",
        artifacts={},
    )
    monkeypatch.setattr(live, "run_live", lambda plan, **_: stopped)
    code = live.main(["--api-key-file", str(key_file), "--out", str(tmp_path / "o")])
    assert code == 1
    assert "stopped after build" in capsys.readouterr().out


# --- replicates (issue #185) -------------------------------------------------


def test_one_replicate_keeps_the_single_ledger_layout(stubbed, tmp_path) -> None:
    result = live.run_live(PLAN, provider=object(), model="fake", out=tmp_path / "run")
    assert result.plan.replicates == 1 and result.replicate_ledgers == {}
    assert all("replicate" not in call for call in stubbed["benchmark"])
    assert result.bootstrap is not None, "the clustered interval is reported whatever K is"


def test_three_replicates_run_every_episode_stage_three_times(stubbed, tmp_path) -> None:
    """Spec §7 item 2's registered plan: k = 3 whole-run replicates of every stage."""
    out = tmp_path / "run"
    plan = PLAN.model_copy(update={"replicates": 3})
    result = live.run_live(plan, provider=object(), model="fake", out=out)

    by_stage: dict[str, list[int]] = {}
    for call in stubbed["benchmark"]:
        stage = call["out"].parent.parent.name
        by_stage.setdefault(stage, []).append(call["replicate"])
    assert by_stage == {"frozen": [1, 2, 3], "positive-only": [1, 2, 3], "online": [1, 2, 3]}

    assert set(result.replicate_ledgers) == {"frozen", "positive-only", "online"}
    assert result.replicate_ledgers["frozen"] == [
        f"frozen/replicate-{r}/ledger.jsonl" for r in (1, 2, 3)
    ]
    for stage, ledgers in result.replicate_ledgers.items():
        assert all((out / path).is_file() for path in ledgers), stage

    frozen = read(out / result.artifacts["frozen_ledger"])
    assert [row.replicate for row in frozen] == [1, 2, 3], "the stage ledger holds every replicate"
    online = read(out / result.artifacts["online_ledger"])
    assert [row.replicate for row in online] == [1, 2, 3]
    assert stubbed["report"] == [out / "frozen.jsonl"], "the report reads the concatenation"
    assert (
        "frozen"
        in json.loads((out / "summary.json").read_text(encoding="utf-8"))["replicate_ledgers"]
    )


def test_the_frozen_library_is_shared_across_replicates(stubbed, tmp_path) -> None:
    plan = PLAN.model_copy(update={"replicates": 2})
    live.run_live(plan, provider=object(), model="fake", out=tmp_path / "run")
    frozen = [call for call in stubbed["benchmark"] if call["arms"] == list(live.FROZEN_ARMS)]
    assert len(frozen) == 2
    assert {call["frozen_library"] for call in frozen} == {tmp_path / "run" / "library-two-sided"}
    online = [call for call in stubbed["benchmark"] if call["arms"] == list(live.ONLINE_ARMS)]
    assert all("frozen_library" not in call for call in online), "each online replicate learns"
    assert len({call["out"].parent for call in online}) == 2, "in its own directory"


def test_the_replicate_count_is_validated(tmp_path) -> None:
    with pytest.raises(ValueError, match="replicates"):
        live.run_live(
            PLAN.model_copy(update={"replicates": 0}),
            provider=object(),
            model="fake",
            out=tmp_path / "run",
        )
    key_file = tmp_path / "key"
    key_file.write_text("k", encoding="utf-8")
    with pytest.raises(SystemExit, match="replicates"):
        live.main(
            ["--api-key-file", str(key_file), "--out", str(tmp_path / "o"), "--replicates", "0"]
        )


def test_the_command_passes_the_replicate_count(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("k", encoding="utf-8")
    seen: dict = {}

    def fake_run(plan, **_):
        seen["plan"] = plan
        raise SystemExit(0)

    monkeypatch.setattr(live, "run_live", fake_run)
    with pytest.raises(SystemExit):
        live.main(
            ["--api-key-file", str(key_file), "--out", str(tmp_path / "o"), "--replicates", "3"]
        )
    assert seen["plan"].replicates == 3
