"""Study 2's population of builds (refusal-population §5), run by a fake `bench.live`.

The fake writes what a finished build leaves (`summary.json`, the two-sided library's
`build.json`) or fails as told, so each of §5's rules is checked without a model: a finished
build, one interrupted and resumed, one that never finishes and is replaced by index 10, a build
that admits nothing and still counts, and a refused account that stops everything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from precondition_library.bench import population as pop
from precondition_library.bench import preregistration


class FakeLive:
    """Stands in for `bench.live`: `script[(configuration, order)]` says what each run does."""

    def __init__(self, script: dict[tuple[str, int], list[str]] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, int, bool]] = []

    def __call__(self, attempt: pop.Attempt, resume: bool) -> tuple[int, str]:
        self.calls.append((attempt.configuration, attempt.order, resume))
        steps = self.script.get((attempt.configuration, attempt.order), ["finish"])
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        directory = Path(attempt.directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "plan.json").write_text("{}", encoding="utf-8")
        if step == "refused":
            return 1, "stopped: the provider refused the account: 401"
        if step == "crash":
            return 1, "Traceback (most recent call last):\nConnectionResetError: reset by peer"
        library = directory / "library-two-sided"
        library.mkdir(exist_ok=True)
        (library / "build.json").write_text(json.dumps({"order": attempt.order}), "utf-8")
        (directory / "summary.json").write_text("{}", encoding="utf-8")
        return (1, "stopped after build") if step == "nothing admitted" else (0, "done")


def test_every_build_runs_once_and_finishes(tmp_path: Path) -> None:
    live = FakeLive()
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", live, jobs=3)
    assert len(population.attempts) == 20
    assert all(a.status == "finished" and a.runs == 1 for a in population.attempts)
    assert sorted((c, b) for c, b, _ in live.calls) == sorted(
        (c, b) for c in ("0", "R") for b in range(10)
    )
    assert all(not resume for _, _, resume in live.calls)
    record = pop.Population.model_validate_json((tmp_path / "builds" / pop.RECORD).read_text())
    assert record == population


def test_a_build_that_admits_nothing_is_valid(tmp_path: Path) -> None:
    live = FakeLive({("R", 3): ["nothing admitted"]})
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", live)
    assert len(pop.valid(population, "R")) == 10, "§5: a build that admits nothing is valid"


def test_an_interrupted_build_is_resumed(tmp_path: Path) -> None:
    live = FakeLive({("0", 4): ["crash", "finish"]})
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", live)
    (build,) = [a for a in population.attempts if (a.configuration, a.order) == ("0", 4)]
    assert build.status == "finished" and build.runs == 2
    assert ("0", 4, False) in live.calls and ("0", 4, True) in live.calls


def test_a_build_that_never_finishes_is_replaced_by_the_next_index(tmp_path: Path) -> None:
    live = FakeLive({("R", 7): ["crash"]})
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", live)
    (failed,) = [a for a in population.attempts if a.status == "failed"]
    assert (failed.configuration, failed.order, failed.runs) == ("R", 7, 1 + pop.RESUMES)
    assert failed.reason == "exit 1: ConnectionResetError: reset by peer"
    (replacement,) = [a for a in population.attempts if a.replaces is not None]
    assert (replacement.configuration, replacement.order, replacement.replaces) == ("R", 10, 7)
    assert replacement.status == "finished"
    assert [a.order for a in pop.valid(population, "R")] == [0, 1, 2, 3, 4, 5, 6, 8, 9, 10]
    assert len(pop.valid(population, "0")) == 10, "the other configuration is untouched"
    assert "R-7 failed after 3 runs" in pop.text(population)
    assert "R-10 replaces R-7" in pop.text(population)


def test_replacements_stop_at_twelve(tmp_path: Path) -> None:
    script = {("0", b): ["crash"] for b in (0, 1, 2, 3, 10, 11, 12)}
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", FakeLive(script))
    assert [
        a.order for a in population.attempts if a.configuration == "0" and a.replaces is not None
    ] == [
        10,
        11,
        12,
    ]
    assert len(pop.valid(population, "0")) == 6, "four failures, three replacements, all failed"


def test_a_refused_account_stops_the_population_and_it_resumes(tmp_path: Path) -> None:
    live = FakeLive({("0", 0): ["refused", "finish"]})
    population = pop.run_population(tmp_path / "builds", tmp_path / "R", live, jobs=1)
    assert population.stopped == f"build 0-0: {pop.REFUSED_ACCOUNT}"
    assert len(live.calls) == 1, "nothing runs after the refusal"
    assert all(a.status == "pending" for a in population.attempts)
    again = pop.run_population(tmp_path / "builds", tmp_path / "R", live, jobs=1)
    assert again.stopped is None
    assert all(a.status == "finished" for a in again.attempts)
    assert ("0", 0, True) in live.calls, "the interrupted build is resumed, not restarted"


def test_finished_builds_are_not_run_again(tmp_path: Path) -> None:
    live = FakeLive()
    pop.run_population(tmp_path / "builds", tmp_path / "R", live)
    count = len(live.calls)
    pop.run_population(tmp_path / "builds", tmp_path / "R", live)
    assert len(live.calls) == count


def test_a_population_keeps_its_refusal_set(tmp_path: Path) -> None:
    pop.run_population(tmp_path / "builds", tmp_path / "R", FakeLive())
    with pytest.raises(ValueError, match="was started with refusal set"):
        pop.run_population(tmp_path / "builds", tmp_path / "other", FakeLive())


def test_the_population_is_bound_by_the_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(preregistration.REGISTRATIONS, pop.REGISTRATION, "0" * 64)
    with pytest.raises(preregistration.UnregisteredError, match="differs"):
        pop.run_population(tmp_path / "builds", tmp_path / "R", FakeLive())
    assert not (tmp_path / "builds").exists()


def test_the_runner_passes_the_registered_options(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[list[str]] = []

    def fake_run(argv, **_):  # type: ignore[no-untyped-def]
        seen.append(argv)

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(pop.subprocess, "run", fake_run)
    runner = pop.live_runner(tmp_path / "R", "DEEPSEEK_API_KEY", None)
    attempt = pop.Attempt(configuration="R", order=4, directory=str(tmp_path / "R-4"))
    runner(attempt, True)
    argv = seen[0]
    assert argv[1:3] == ["-m", "precondition_library.bench.live"]
    assert argv[argv.index("--api-key-env") + 1] == "DEEPSEEK_API_KEY"
    assert "--primary-only" in argv and argv[argv.index("--build-order") + 1] == "4"
    assert argv[argv.index("--refusal-set") + 1] == str(tmp_path / "R")
    assert argv[-1] == "--resume"
    runner(pop.Attempt(configuration="0", order=4, directory=str(tmp_path / "0-4")), False)
    assert "--refusal-set" not in seen[1] and "--resume" not in seen[1]
