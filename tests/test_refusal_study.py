"""Study 2's runner (refusal-population §3.4, §6–§10): its figures by hand, then end to end.

The figures are checked on four hand-made cases in two repositories. The run is checked on
study 1's fixture history standing in for list E, with the targets lowered so mining stops
after one repository, and with copies of a committed library standing in for the population.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from test_real_merges import history  # noqa: F401  (the module-scoped fixture)

from precondition_library.bench import preregistration
from precondition_library.bench import refusal_population as rp
from precondition_library.bench import refusal_set as rs
from precondition_library.bench import refusal_study as study
from precondition_library.bench.real_merges import LIBRARIES, Case, Label
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox


def test_the_evaluation_list_is_the_registered_one() -> None:
    text = preregistration.document(rs.REGISTRATION).read_text(encoding="utf-8")
    section = text.split("**Evaluation (E), in order:**", 1)[1].split("\n\nNone of these", 1)[0]
    assert list(study.EVALUATION) == re.findall(r"^\d+\. \[`([^`]+)`\]", section, re.MULTILINE)
    assert "at least 100 inexpressible conflicts and at least 60 clean cases" in text
    assert "from at least 6\nrepositories with a case" in text
    assert (study.TARGET_INEXPRESSIBLE, study.TARGET_CLEAN, study.MIN_REPOSITORIES) == (100, 60, 6)
    assert study.CAP == 40


# --- the figures, by hand ---------------------------------------------------------------------


def _case(index: int, repo: str, kind: str) -> Case:
    return Case(
        index=index,
        repo=repo,
        kind=kind,  # type: ignore[arg-type]
        merge=f"{index:040x}",
        first="f" * 40,
        second="s" * 40,
        base="b" * 40,
        conflicted=["Cargo.lock"] if kind == "positive" else [],
    )


CASES = [
    _case(0, "a", "positive"),
    _case(1, "a", "negative"),
    _case(2, "b", "positive"),
    _case(3, "b", "negative"),
    _case(4, "b", "positive"),
]
LABELS = [
    Label(index=0, acceptable=[], descriptive="regenerated"),
    Label(index=1, acceptable=["merge"], descriptive="clean merge reproduced"),
    Label(index=2, acceptable=[], descriptive="other"),
    Label(index=3, acceptable=["merge"], descriptive="clean merge reproduced"),
    Label(index=4, acceptable=["take_upstream"], descriptive="matches take_upstream"),
]


def _row(index: int, zero: str | None, refusal: str | None, c0: str | None, cr: str | None):  # type: ignore[no-untyped-def]
    return study.StudyDecisions(
        index=index,
        zero=[zero],
        refusal=[refusal],
        control_zero=(c0, 1.0),
        control_refusal=(cr, 1.0),
    )


# Configuration 0's build fires keep_local everywhere; R's fires merge on the clean cases and
# nothing on a conflict. Control-0 fires merge everywhere; Control-R fires on inexpressible
# case 2 only.
ROWS = [
    _row(0, "keep_local", None, "merge", None),
    _row(1, "keep_local", "merge", "merge", "merge"),
    _row(2, "keep_local", None, "merge", "keep_local"),
    _row(3, "keep_local", "merge", "merge", "merge"),
    _row(4, "keep_local", "take_upstream", "merge", None),
]
BUILDS = [
    study.Build(configuration="0", order=0, library="zero", library_hash="z"),
    study.Build(configuration="R", order=0, library="refusal", library_hash="r"),
]


def test_each_case_is_counted_by_its_kind() -> None:
    assert [study.kind_of(c, lab) for c, lab in zip(CASES, LABELS, strict=True)] == [
        "inexpressible",
        "clean",
        "inexpressible",
        "clean",
        "other",
    ]
    assert study.counts(CASES, LABELS) == study.Counts(
        inexpressible=2, clean=2, other=1, repositories_with_a_case=2
    )


def test_the_report_by_hand() -> None:
    found = study.report(CASES, LABELS, ROWS, BUILDS, refusal_set="x" * 64, refusal_collisions=0)
    assert found.control_zero_fire_rate == 1.0
    assert found.control_refusal_fire_rate == 0.5
    # H1: f(Control-R) - f(R) = 0.5 - 0; H2: f(Control-0) - f(0) = 1 - 1; H3: f(0) - f(R) = 1;
    # H4: right(R) - right(0) on clean cases = 1 - 0.
    statistics = [
        found.hypotheses.h1.statistic,
        found.hypotheses.h2.statistic,
        found.hypotheses.h3.statistic,
        found.hypotheses.h4.statistic,
    ]
    assert statistics == [0.5, 0.0, 1.0, 1.0]
    zero, refusal = found.builds
    assert (zero.fire_rate, zero.clean_right_rate) == (1.0, 0.0)
    assert (refusal.fire_rate, refusal.clean_right_rate) == (0.0, 1.0)
    assert zero.against_control.statistic == 0.0 and not zero.beats_control
    assert refusal.against_control.statistic == 0.5
    assert found.spread == {"0": rp.spread([1.0]), "R": rp.spread([0.0])}


def test_a_short_study_is_underpowered_and_says_why() -> None:
    found = study.report(CASES, LABELS, ROWS, BUILDS, refusal_set="x" * 64, refusal_collisions=0)
    assert found.underpowered
    assert found.underpowered_because == [
        "the evaluation set has 2 inexpressible and 2 clean cases from 2 repositories, short "
        "of §3.4's 100, 60 and 6",
        "configuration 0 has 1 valid builds, fewer than 8",
        "configuration R has 1 valid builds, fewer than 8",
    ]
    assert [d.rule for d in found.decisions] == ["1 power"]
    summary = study.text(found)
    assert "underpowered: configuration R has 1 valid builds" in summary
    assert "rule 1 power: underpowered" in summary


# --- the builds -------------------------------------------------------------------------------


def _library(tmp_path: Path, name: str, **manifest: object) -> Path:
    """A copy of a committed library whose build.json says what `manifest` says."""
    copy = tmp_path / name
    shutil.copytree(preregistration.REPOSITORY / LIBRARIES[1], copy)
    recorded = json.loads((copy / "build.json").read_text(encoding="utf-8"))
    recorded.update(manifest)
    (copy / "build.json").write_text(json.dumps(recorded), encoding="utf-8")
    return copy


def test_a_build_is_read_with_its_configuration(tmp_path: Path) -> None:
    zero = study.read_build(_library(tmp_path, "z", order=3, refusal_set=None), "0", "d" * 64)
    assert (zero.configuration, zero.order) == ("0", 3)
    refusal = study.read_build(
        _library(tmp_path, "r", order=3, refusal_set="d" * 64), "R", "d" * 64
    )
    assert refusal.configuration == "R"


@pytest.mark.parametrize(
    ("manifest", "configuration", "message"),
    [
        ({"order": None, "refusal_set": None}, "0", "without a build order"),
        ({"order": 1, "refusal_set": "e" * 64}, "R", "configuration R needs"),
        ({"order": 1, "refusal_set": "d" * 64}, "0", "configuration 0 needs None"),
        ({"order": 1, "refusal_set": None}, "R", "configuration R needs"),
    ],
)
def test_a_build_that_is_not_its_configurations_is_refused(
    tmp_path: Path, manifest: dict, configuration: str, message: str
) -> None:
    path = _library(tmp_path, "x", **manifest)
    with pytest.raises(ValueError, match=message):
        study.read_build(path, configuration, "d" * 64)  # type: ignore[arg-type]


def test_an_unfinished_build_is_refused(tmp_path: Path) -> None:
    path = _library(tmp_path, "x", order=1, refusal_set=None)
    (path / "build.json").unlink()
    with pytest.raises(ValueError, match="not a finished build"):
        study.read_build(path, "0", "d" * 64)


# --- end to end -------------------------------------------------------------------------------


def _fault_states() -> list[StateFingerprint]:
    states = []
    for faults in ([], ["lockfile_conflict"], ["diverged"]):
        box = build_sandbox(2, faults)
        try:
            states.append(StateFingerprint.observe(box))
        finally:
            box.destroy()
    return states


@pytest.fixture
def run(
    history: dict[str, object],  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """R mined from the fixture, two libraries per configuration, and list E of two
    repositories that are both the fixture, with targets the first one meets."""
    fetched: list[str] = []

    def fetch(host: object) -> Path:
        fetched.append(str(host))
        copy = tmp_path / f"cache-{len(fetched)}.git"
        shutil.copytree(history["cache"], copy)  # type: ignore[arg-type]
        return copy

    for module in (rs, study):
        monkeypatch.setattr(module, "pin", lambda repo: ("main", history["tip"]))
        monkeypatch.setattr(module, "fetch_real_host", fetch)
    monkeypatch.setattr(rs, "ADMISSION", ("example/admission",))
    refusal_dir = tmp_path / "R"
    rs.mine_refusal_set(refusal_dir)
    digest = rs.digest(refusal_dir)
    monkeypatch.setattr(study, "EVALUATION", ("example/first", "example/second"))
    monkeypatch.setattr(study, "TARGET_INEXPRESSIBLE", 1)
    monkeypatch.setattr(study, "TARGET_CLEAN", 1)
    monkeypatch.setattr(study, "MIN_REPOSITORIES", 1)
    training = _fault_states()
    monkeypatch.setattr(study, "training_states", lambda: training)
    zero = [_library(tmp_path, f"zero-{b}", order=b, refusal_set=None) for b in (0, 1)]
    refusal = [_library(tmp_path, f"r-{b}", order=b, refusal_set=digest) for b in (0, 1)]
    out = tmp_path / "out"
    fetched.clear()
    result = study.evaluate(out, refusal_dir, zero, refusal)
    return {
        "out": out,
        "result": result,
        "fetched": fetched,
        "args": (out, refusal_dir, zero, refusal),
        "history": history,
    }


def test_mining_stops_once_the_targets_are_met(run: dict[str, object]) -> None:
    fetched = run["fetched"]
    assert isinstance(fetched, list) and len(fetched) == 1, "the second repository is never mined"
    manifest = study.EvaluationManifest.model_validate_json(
        (run["out"] / "manifest.json").read_text("utf-8")  # type: ignore[operator]
    )
    assert [r.repo for r in manifest.repositories] == ["example/first"]
    fixture = run["history"]
    assert isinstance(fixture, dict)
    assert len(manifest.cases) == len(fixture["cases"]), "every fixture case, under the cap"


def test_every_case_is_decided_by_every_dispatcher_and_labelled(run: dict[str, object]) -> None:
    out = run["out"]
    assert isinstance(out, Path)
    rows = [
        study.StudyDecisions.model_validate_json(line)
        for line in (out / "decisions.jsonl").read_text("utf-8").splitlines()
    ]
    labels = [
        Label.model_validate_json(line)
        for line in (out / "labels.jsonl").read_text("utf-8").splitlines()
    ]
    assert [row.index for row in rows] == [lab.index for lab in labels]
    assert all(len(row.zero) == 2 and len(row.refusal) == 2 for row in rows)
    # The two copies of one library decide alike, in both configurations.
    assert all(row.zero[0] == row.zero[1] == row.refusal[0] == row.refusal[1] for row in rows)
    result = run["result"]
    assert isinstance(result, study.StudyReport)
    assert result.counts == study.Counts(
        inexpressible=2, clean=2, other=2, repositories_with_a_case=1
    )
    assert result.valid_builds == {"0": 2, "R": 2}
    builds = json.loads((out / "builds.json").read_text("utf-8"))
    assert [(b["configuration"], b["order"]) for b in builds] == [
        ("0", 0),
        ("0", 1),
        ("R", 0),
        ("R", 1),
    ]


def test_the_report_is_what_its_files_say(run: dict[str, object]) -> None:
    """The report recomputed from the written files alone is the one the run wrote."""
    out = run["out"]
    assert isinstance(out, Path)
    manifest = study.EvaluationManifest.model_validate_json((out / "manifest.json").read_text())
    labels = [Label.model_validate_json(x) for x in (out / "labels.jsonl").read_text().splitlines()]
    rows = [
        study.StudyDecisions.model_validate_json(x)
        for x in (out / "decisions.jsonl").read_text().splitlines()
    ]
    builds = [study.Build.model_validate(b) for b in json.loads((out / "builds.json").read_text())]
    result = run["result"]
    assert isinstance(result, study.StudyReport)
    again = study.report(
        manifest.cases,
        labels,
        rows,
        builds,
        refusal_set=result.refusal_set,
        refusal_collisions=result.refusal_collisions,
    )
    assert again == result
    assert study.StudyReport.model_validate_json((out / "report.json").read_text()) == result
    assert (out / "summary.txt").read_text() == study.text(result)


def test_an_interrupted_run_resumes_without_mining_again(run: dict[str, object]) -> None:
    out, refusal_dir, zero, refusal = run["args"]  # type: ignore[misc]
    fetched = run["fetched"]
    assert isinstance(fetched, list)
    before = len(fetched)
    (out / "report.json").unlink()
    again = study.evaluate(out, refusal_dir, zero, refusal)
    assert len(fetched) == before
    assert again == run["result"]


def test_the_controls_differ_only_by_the_refusal_states(run: dict[str, object]) -> None:
    """Control-R declines R's states and agrees with Control-0 on training states R does not
    repeat. The training states here are a fault-free and a diverged state, which no lock-file
    conflict can share features with on any git."""
    _, refusal_dir, _, _ = run["args"]  # type: ignore[misc]
    _, refusal_states = rs.load(refusal_dir)
    training = [s for s in _fault_states() if not s.sync_would_conflict]
    assert len(training) == 2
    assert study.collisions(training, refusal_states) == 0
    zero, refusal = study.controls(training, refusal_states)
    for state in refusal_states:
        assert refusal.decide_library(state) == (None, 0.0), "Control-R declines R's states"
    for state in training:
        assert zero.decide_library(state) == refusal.decide_library(state)


def test_a_refusal_state_that_repeats_a_training_state_takes_the_majority_label() -> None:
    """ADR-0054 item 6: Control-R cannot tell apart identical feature rows, so it predicts the
    label they hold more often. One training lock-file state against two copies of it as
    refusals: "fire nothing" wins, and both copies count as collisions."""
    (lock,) = [s for s in _fault_states() if s.sync_would_conflict]
    zero, refusal = study.controls([lock], [lock, lock])
    assert zero.decide_library(lock)[0] is not None, "Control-0 fires on its training state"
    assert refusal.decide_library(lock)[0] is None
    assert study.collisions([lock], [lock, lock]) == 2


def test_evaluation_refuses_without_the_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, rs.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        study.evaluate(tmp_path / "out", tmp_path / "R", [], [])
    assert not (tmp_path / "out").exists()


def test_the_command_line() -> None:
    with pytest.raises(SystemExit):
        study.main(["evaluate", "--refusal-set", "R"])
