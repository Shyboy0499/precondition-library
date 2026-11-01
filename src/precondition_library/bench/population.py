"""Study 2's population of builds, run as the registration says (refusal-population §5).

Each build is one `bench.live --primary-only --build-order b` run, with `--refusal-set` under
configuration R, in its own directory `<out>/<configuration>-<b>`. This module runs them, several
at a time, and keeps `population.json`, the record of every attempt.

**Finished.** A build is finished when its run wrote `summary.json` and its two-sided library's
`build.json`. That holds when the build admitted no program as well: `bench.live` then stops after
the build and exits 1, and §5 counts it as a valid build that declines everything.

**Resumed, then replaced.** A build that stops for a reason outside the method (a provider error,
an interruption) is run again with `--resume`, up to `RESUMES` times. One that still does not
finish is recorded as failed with its reason, and the configuration's next index replaces it:
10, then 11, then 12 (§5). A failed build's directory is kept for the report.

**Stopped.** If the provider refuses the account, no later call can succeed, so the population
stops at once and says so. Builds already finished stay finished, and running it again resumes
the rest.

    python -m precondition_library.bench.population \\
        --out results/refusal-population-<date>/builds \\
        --refusal-set results/refusal-population-2026-11-01/R \\
        --api-key-env DEEPSEEK_API_KEY --jobs 2

The key is read by `bench.live` from the environment variable it is given, never from here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .preregistration import require
from .refusal_set import REGISTRATION

Configuration = Literal["0", "R"]
CONFIGURATIONS: tuple[Configuration, ...] = ("0", "R")
ORDERS = tuple(range(10))
REPLACEMENTS = (10, 11, 12)
RESUMES = 2
"""Runs after the first: an interrupted build is resumed at most this many times."""
REFUSED_ACCOUNT = "the provider refused the account"
"""What `bench.live` prints when the endpoint refuses the key (`ProviderAuthError`)."""
RECORD = "population.json"


class Attempt(BaseModel):
    configuration: Configuration
    order: int
    directory: str
    runs: int = 0
    status: Literal["pending", "finished", "failed"] = "pending"
    reason: str | None = None
    replaces: int | None = None
    """The index this build replaces, for 10, 11 and 12."""


class Population(BaseModel):
    refusal_set: str
    attempts: list[Attempt]
    stopped: str | None = None


Runner = Callable[[Attempt, bool], tuple[int, str]]
"""Run one build, resuming it or not; return its exit code and the end of its output."""


def finished(directory: Path) -> bool:
    return (directory / "summary.json").is_file() and (
        directory / "library-two-sided" / "build.json"
    ).is_file()


def live_runner(refusal_set: Path, api_key_env: str, model: str | None) -> Runner:
    """Each build as a `bench.live` process, so a crash in one never takes another with it."""

    def run(attempt: Attempt, resume: bool) -> tuple[int, str]:
        argv = [
            sys.executable,
            "-m",
            "precondition_library.bench.live",
            "--api-key-env",
            api_key_env,
            "--primary-only",
            "--build-order",
            str(attempt.order),
            "--out",
            attempt.directory,
        ]
        if attempt.configuration == "R":
            argv += ["--refusal-set", str(refusal_set)]
        if model is not None:
            argv += ["--model", model]
        if resume:
            argv.append("--resume")
        log = Path(attempt.directory + ".log")
        with log.open("a", encoding="utf-8") as handle:
            done = subprocess.run(argv, stdout=handle, stderr=subprocess.STDOUT, check=False)
        tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        return done.returncode, tail

    return run


def _load(out: Path, refusal_set: Path) -> Population:
    record = out / RECORD
    if record.is_file():
        population = Population.model_validate_json(record.read_text("utf-8"))
        if population.refusal_set != str(refusal_set):
            raise ValueError(f"{record} was started with refusal set {population.refusal_set}")
        population.stopped = None
        return population
    return Population(
        refusal_set=str(refusal_set),
        attempts=[
            Attempt(configuration=c, order=b, directory=str(out / f"{c}-{b}"))
            for c in CONFIGURATIONS
            for b in ORDERS
        ],
    )


def run_population(
    out: Path,
    refusal_set: Path,
    runner: Runner,
    *,
    jobs: int = 1,
) -> Population:
    """Run every pending build, resuming and replacing as §5 says; return the record."""
    require(REGISTRATION)
    out.mkdir(parents=True, exist_ok=True)
    population = _load(out, refusal_set)
    lock = threading.Lock()
    stop = threading.Event()

    def save() -> None:
        (out / RECORD).write_text(population.model_dump_json(indent=2) + "\n", "utf-8")

    def build(attempt: Attempt) -> None:
        directory = Path(attempt.directory)
        while not stop.is_set():
            if finished(directory):
                with lock:
                    attempt.status = "finished"
                    attempt.reason = None
                    save()
                return
            if attempt.runs > RESUMES:
                with lock:
                    attempt.status = "failed"
                    replacement = _replace(population, attempt)
                    save()
                if replacement is not None:
                    build(replacement)
                return
            resume = directory.is_dir() and (directory / "plan.json").is_file()
            code, tail = runner(attempt, resume)
            with lock:
                attempt.runs += 1
                if REFUSED_ACCOUNT in tail:
                    population.stopped = (
                        f"build {attempt.configuration}-{attempt.order}: {REFUSED_ACCOUNT}"
                    )
                    stop.set()
                elif not finished(directory):
                    last = tail.strip().splitlines()[-1] if tail.strip() else "no output"
                    attempt.reason = f"exit {code}: {last}"
                save()

    pending = [a for a in population.attempts if a.status == "pending"]
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        list(pool.map(build, pending))
    save()
    return population


def _replace(population: Population, failed: Attempt) -> Attempt | None:
    """The configuration's next replacement index, recorded as replacing `failed`; None when
    10, 11 and 12 are all used."""
    used = {a.order for a in population.attempts if a.configuration == failed.configuration}
    for index in REPLACEMENTS:
        if index not in used:
            directory = Path(failed.directory).with_name(f"{failed.configuration}-{index}")
            replacement = Attempt(
                configuration=failed.configuration,
                order=index,
                directory=str(directory),
                replaces=failed.order,
            )
            population.attempts.append(replacement)
            return replacement
    return None


def valid(population: Population, configuration: Configuration) -> list[Attempt]:
    """The finished builds of one configuration: what `refusal_study evaluate` is given."""
    return [
        a
        for a in population.attempts
        if a.configuration == configuration and a.status == "finished"
    ]


def text(population: Population) -> str:
    lines = []
    for configuration in CONFIGURATIONS:
        done = valid(population, configuration)
        failed = [
            a
            for a in population.attempts
            if a.configuration == configuration and a.status == "failed"
        ]
        lines.append(
            f"configuration {configuration}: {len(done)} finished"
            + (f", {len(failed)} failed" if failed else "")
        )
        for a in failed:
            lines.append(f"  {configuration}-{a.order} failed after {a.runs} runs: {a.reason}")
        for a in done:
            if a.replaces is not None:
                lines.append(f"  {configuration}-{a.order} replaces {configuration}-{a.replaces}")
    if population.stopped:
        lines.append(f"stopped: {population.stopped}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.population")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--refusal-set", type=Path, required=True, metavar="DIR")
    parser.add_argument(
        "--api-key-env", required=True, metavar="NAME", help="environment variable holding the key"
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--jobs", type=int, default=1, help="builds run at once (default 1)")
    args = parser.parse_args(argv)
    population = run_population(
        args.out,
        args.refusal_set,
        live_runner(args.refusal_set, args.api_key_env, args.model),
        jobs=args.jobs,
    )
    print(text(population), end="")
    return 1 if population.stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
