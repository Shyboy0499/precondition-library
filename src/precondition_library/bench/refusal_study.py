"""Study 2's runner (`docs/preregistration/refusal-population.md`, §3.4 and §6–§10).

Nothing here runs before `preregistration.require("refusal-population")` has passed. The
study's steps, in the registration's order (§4):

3. `mine-refusals` mines and freezes R (`bench.refusal_set`).
4. The 20 builds are `bench.live --primary-only --build-order b`, with `--refusal-set` for
   configuration R. Each library's `build.json` records its order and, under R, the frozen
   set's SHA-256.
5. Both controls are fitted here, deterministically: Control-0 as study 1 fitted the registered
   control, on the build's 56 states, and Control-R on those and R's states, labelled "fire
   nothing" (`StateClassifier.fit(..., refusals=...)`).
6. `evaluate` mines list E in order, only after the libraries exist, until §3.4's targets are
   met; decides every case with every library and both controls; and labels it.
7. It applies §9's rules in order (`bench.refusal_population`) and writes §10's files.

**Mining E (§3.4).** A case, its state, its exclusions and its label are study 1's
(`bench.real_merges`, Amendment 1). Mining stops before the next repository once there are
`TARGET_INEXPRESSIBLE` inexpressible conflicts and `TARGET_CLEAN` clean cases from
`MIN_REPOSITORIES` repositories with a case. No repository contributes more than `CAP` cases;
past that, its most recent are kept, conflicted and clean in equal number, as study 1's
`_capped` keeps them. `CAP` is 25% of the targets' sum, 160, as study 1 took 25% of its target.
Each repository is written under `repos/` as it finishes, and its history removed, so the disk
holds one at a time and an interrupted run resumes.

**Deciding (§6).** Arm 3, per library: the first program whose preconditions all hold on the
case's state, as study 1 decided. Each control fires what `decide_library` predicts. A fire is
right when it is in the case's acceptable set.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..library import Library
from ..runtime.probes import evaluate_preconditions
from ..sandbox import Sandbox, fetch_real_host
from ..signatures import StateFingerprint
from . import refusal_population as rp
from .admit_set import admit_seeds
from .heldout import HELD_OUT_FAULTS
from .library_pairs import _measured_intents
from .preregistration import REPOSITORY, require
from .real_merges import (
    Case,
    Exclusion,
    Label,
    Repository,
    _capped,
    build_state,
    host,
    label,
    mine,
    pin,
)
from .refusal_set import REGISTRATION, digest, load, mine_refusal_set
from .state_classifier import StateClassifier, _states, features

EVALUATION = (
    "openproject/openproject",
    "PrestaShop/PrestaShop",
    "home-assistant/frontend",
    "rust-lang/rust-analyzer",
    "getredash/redash",
    "zellij-org/zellij",
    "forem/forem",
    "zulip/zulip",
    "lapce/lapce",
    "magento/magento2",
    "microsoft/vscode",
    "elastic/kibana",
)
"""List E, in the registration's order (§3.1)."""

TARGET_INEXPRESSIBLE = 100
TARGET_CLEAN = 60
MIN_REPOSITORIES = 6
CAP_SHARE = 0.25
CAP = int(CAP_SHARE * (TARGET_INEXPRESSIBLE + TARGET_CLEAN))
"""At most 40 cases from one repository (§3.4)."""

Configuration = Literal["0", "R"]


class Build(BaseModel):
    """One frozen library of the population, as its `build.json` describes it."""

    configuration: Configuration
    order: int
    library: str
    library_hash: str


def read_build(path: Path, configuration: Configuration, refusal_digest: str) -> Build:
    """A finished build's two-sided library, checked against its configuration.

    `build.json` is written when a build completes, so a library without one is not a valid
    build. A configuration R library must have been gated by this refusal set, and a
    configuration 0 library by none.
    """
    manifest_path = path / "build.json"
    if not manifest_path.is_file():
        raise ValueError(f"{path}: no build.json, so not a finished build")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("order") is None:
        raise ValueError(f"{path}: built without a build order, so not one of study 2's builds")
    expected = refusal_digest if configuration == "R" else None
    if manifest.get("refusal_set") != expected:
        raise ValueError(
            f"{path}: gated by refusal set {manifest.get('refusal_set')!r}, but configuration "
            f"{configuration} needs {expected!r}"
        )
    return Build(
        configuration=configuration,
        order=manifest["order"],
        library=str(path),
        library_hash=Library(path).library_hash(),
    )


class EvaluationManifest(BaseModel):
    repositories: list[Repository]
    cases: list[Case]
    exclusions: list[Exclusion]


class StudyDecisions(BaseModel):
    """What every dispatcher fired on one case: per build in each configuration, and each
    control with its probability."""

    index: int
    zero: list[str | None]
    refusal: list[str | None]
    control_zero: tuple[str | None, float]
    control_refusal: tuple[str | None, float]


class _RepositoryPart(BaseModel):
    repository: Repository
    cases: list[Case]
    exclusions: list[Exclusion]
    labels: list[Label]
    decisions: list[StudyDecisions]
    states: list[StateFingerprint]


def training_states() -> list[StateFingerprint]:
    """The 56 states study 1 fitted its control on: the build's admit seeds, and fault-free."""
    built = _states(HELD_OUT_FAULTS, {fault: admit_seeds(fault) for fault in HELD_OUT_FAULTS})
    return [state for _, _, state in built]


def controls(
    training: Sequence[StateFingerprint], refusal_states: Sequence[StateFingerprint]
) -> tuple[StateClassifier, StateClassifier]:
    """Control-0 and Control-R (§6): the same trees, Control-R's also fitted on R's states
    labelled "fire nothing". Neither is refit on evaluation data."""
    intents = _measured_intents(HELD_OUT_FAULTS)
    return (
        StateClassifier(intents).fit(training),
        StateClassifier(intents).fit(training, refusals=refusal_states),
    )


def collisions(
    training: Sequence[StateFingerprint], refusal_states: Sequence[StateFingerprint]
) -> int:
    """How many of R's states have the features of a training state, which Control-R cannot
    tell apart from it (`StateClassifier.fit`). Reported, not acted on."""
    trained = [features(state) for state in training]
    return sum(features(state) in trained for state in refusal_states)


def kind_of(case: Case, lab: Label) -> rp.Kind:
    if case.kind == "negative":
        return "clean"
    return "other" if lab.acceptable else "inexpressible"


def _arm3(library: Library, box: Sandbox) -> str | None:
    accepted = library.match_preconditions(box)
    return accepted[0].variant if accepted else None


def _decide_repository(
    repo: str,
    first_index: int,
    zero: Sequence[Library],
    refusal: Sequence[Library],
    control_zero: StateClassifier,
    control_refusal: StateClassifier,
) -> _RepositoryPart:
    branch, tip = pin(repo)
    cache = fetch_real_host(host(repo, tip))
    try:
        summary, mined, excluded = mine(repo, cache, branch, tip)
        kept = _capped(mined, cache, CAP)
        kept = [case.model_copy(update={"index": first_index + i}) for i, case in enumerate(kept)]
        cases: list[Case] = []
        labels: list[Label] = []
        decided: list[StudyDecisions] = []
        states: list[StateFingerprint] = []
        for case in kept:
            try:
                box = build_state(case, cache, branch)
            except subprocess.CalledProcessError:
                excluded.append(
                    Exclusion(repo=case.repo, merge=case.merge, reason="state not built")
                )
                continue
            try:
                state = StateFingerprint.observe(box)
                decided.append(
                    StudyDecisions(
                        index=case.index,
                        zero=[_arm3(library, box) for library in zero],
                        refusal=[_arm3(library, box) for library in refusal],
                        control_zero=control_zero.decide_library(state),
                        control_refusal=control_refusal.decide_library(state),
                    )
                )
            finally:
                box.destroy()
            cases.append(case)
            labels.append(label(case, cache, amendment=1))
            states.append(state)
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    return _RepositoryPart(
        repository=summary.model_copy(
            update={
                "positives": sum(c.kind == "positive" for c in cases),
                "negatives": sum(c.kind == "negative" for c in cases),
                "exclusions": len(excluded),
            }
        ),
        cases=cases,
        exclusions=excluded,
        labels=labels,
        decisions=decided,
        states=states,
    )


class Counts(BaseModel):
    inexpressible: int
    clean: int
    other: int
    repositories_with_a_case: int


def counts(cases: Sequence[Case], labels: Sequence[Label]) -> Counts:
    kinds = [kind_of(case, lab) for case, lab in zip(cases, labels, strict=True)]
    return Counts(
        inexpressible=kinds.count("inexpressible"),
        clean=kinds.count("clean"),
        other=kinds.count("other"),
        repositories_with_a_case=len({case.repo for case in cases}),
    )


def targets_met(found: Counts) -> bool:
    return (
        found.inexpressible >= TARGET_INEXPRESSIBLE
        and found.clean >= TARGET_CLEAN
        and found.repositories_with_a_case >= MIN_REPOSITORIES
    )


class BuildFigures(BaseModel):
    """§7's figures beside the intervals: one build's own rate and its margin over its
    configuration's control, with a repository-clustered interval."""

    configuration: Configuration
    order: int
    fire_rate: float | None
    clean_right_rate: float | None
    against_control: rp.Estimate
    beats_control: bool
    """Its margin's interval lies above 0."""


class StudyReport(BaseModel):
    counts: Counts
    valid_builds: dict[str, int]
    underpowered: bool
    underpowered_because: list[str]
    refusal_set: str
    refusal_collisions: int
    control_zero_fire_rate: float | None
    control_refusal_fire_rate: float | None
    hypotheses: rp.Hypotheses
    decisions: list[rp.Decision]
    builds: list[BuildFigures]
    spread: dict[str, dict[str, float]]


def _fires(
    rows: Sequence[StudyDecisions], labels: Sequence[Label], fired: Sequence[str | None]
) -> rp.Decisions:
    """One dispatcher's decisions, `fired[i]` being what it fired on `rows[i]`'s case."""
    acceptable = {lab.index: set(lab.acceptable) for lab in labels}
    return {
        row.index: rp.Fire(
            fired=variant is not None,
            right=variant is not None and variant in acceptable[row.index],
        )
        for row, variant in zip(rows, fired, strict=True)
    }


def _margin(cases: Sequence[rp.Case], build: rp.Decisions, control: rp.Decisions) -> rp.Estimate:
    """One build's margin over its control, its interval clustered by repository only."""

    def statistic(
        drawn: Sequence[rp.Case], groups: Sequence[Sequence[rp.Decisions]]
    ) -> float | None:
        return rp.against_control(groups[0], control, drawn)

    return rp.two_level_bootstrap(cases, [[build]], statistic)


def report(
    cases: Sequence[Case],
    labels: Sequence[Label],
    rows: Sequence[StudyDecisions],
    builds: Sequence[Build],
    *,
    refusal_set: str,
    refusal_collisions: int,
) -> StudyReport:
    """§7's estimates and §9's decisions from the recorded decisions and labels."""
    found = counts(cases, labels)
    study = [
        rp.Case(index=case.index, repo=case.repo, kind=kind_of(case, lab))
        for case, lab in zip(cases, labels, strict=True)
    ]
    zero_builds = [b for b in builds if b.configuration == "0"]
    refusal_builds = [b for b in builds if b.configuration == "R"]
    zero = [_fires(rows, labels, [r.zero[i] for r in rows]) for i in range(len(zero_builds))]
    refusal = [
        _fires(rows, labels, [r.refusal[i] for r in rows]) for i in range(len(refusal_builds))
    ]
    control_zero = _fires(rows, labels, [r.control_zero[0] for r in rows])
    control_refusal = _fires(rows, labels, [r.control_refusal[0] for r in rows])
    because = []
    if not targets_met(found):
        because.append(
            f"the evaluation set has {found.inexpressible} inexpressible and {found.clean} clean "
            f"cases from {found.repositories_with_a_case} repositories, short of §3.4's "
            f"{TARGET_INEXPRESSIBLE}, {TARGET_CLEAN} and {MIN_REPOSITORIES}"
        )
    for name, group in (("0", zero_builds), ("R", refusal_builds)):
        if len(group) < rp.MIN_VALID_BUILDS:
            because.append(
                f"configuration {name} has {len(group)} valid builds, fewer than "
                f"{rp.MIN_VALID_BUILDS}"
            )
    hypotheses = rp.estimate(study, zero, refusal, control_zero, control_refusal)
    figures = []
    for group, decided, control in (
        (zero_builds, zero, control_zero),
        (refusal_builds, refusal, control_refusal),
    ):
        for build, one in zip(group, decided, strict=True):
            margin = _margin(study, one, control)
            figures.append(
                BuildFigures(
                    configuration=build.configuration,
                    order=build.order,
                    fire_rate=rp.fire_rate(one, study),
                    clean_right_rate=rp.clean_right_rate(one, study),
                    against_control=margin,
                    beats_control=margin.interval is not None and margin.interval.low > 0,
                )
            )
    spread = {
        name: rp.spread([f for f in (rp.fire_rate(d, study) for d in group) if f is not None])
        for name, group in (("0", zero), ("R", refusal))
        if any(rp.fire_rate(d, study) is not None for d in group)
    }
    return StudyReport(
        counts=found,
        valid_builds={"0": len(zero_builds), "R": len(refusal_builds)},
        underpowered=bool(because),
        underpowered_because=because,
        refusal_set=refusal_set,
        refusal_collisions=refusal_collisions,
        control_zero_fire_rate=rp.fire_rate(control_zero, study),
        control_refusal_fire_rate=rp.fire_rate(control_refusal, study),
        hypotheses=hypotheses,
        decisions=rp.decide(
            hypotheses, underpowered=bool(because), zero=zero, refusal=refusal, cases=study
        ),
        builds=figures,
        spread=spread,
    )


def evaluate(
    out: Path,
    refusal_dir: Path,
    zero_paths: Sequence[Path],
    refusal_paths: Sequence[Path],
) -> StudyReport:
    """§4 steps 5–7: fit the controls, mine and decide list E, estimate and decide."""
    require(REGISTRATION)
    refusal_digest = digest(refusal_dir)
    _, refusal_states = load(refusal_dir)
    builds = [read_build(path, "0", refusal_digest) for path in zero_paths] + [
        read_build(path, "R", refusal_digest) for path in refusal_paths
    ]
    loaded = {
        b.library: Library(Path(b.library), evaluate_preconditions=evaluate_preconditions)
        for b in builds
    }
    zero = [loaded[b.library] for b in builds if b.configuration == "0"]
    refusal = [loaded[b.library] for b in builds if b.configuration == "R"]
    training = training_states()
    control_zero, control_refusal = controls(training, refusal_states)
    done = out / "repos"
    done.mkdir(parents=True, exist_ok=True)
    parts: list[_RepositoryPart] = []
    for repo in EVALUATION:
        so_far = [case for part in parts for case in part.cases]
        if targets_met(counts(so_far, [lab for part in parts for lab in part.labels])):
            break
        written = done / f"{repo.replace('/', '__')}.json"
        if written.is_file():
            part = _RepositoryPart.model_validate_json(written.read_text("utf-8"))
        else:
            part = _decide_repository(
                repo, len(so_far), zero, refusal, control_zero, control_refusal
            )
            written.write_text(part.model_dump_json() + "\n", "utf-8")
        parts.append(part)
    cases = [case for part in parts for case in part.cases]
    labels = [lab for part in parts for lab in part.labels]
    rows = [row for part in parts for row in part.decisions]
    manifest = EvaluationManifest(
        repositories=[part.repository for part in parts],
        cases=cases,
        exclusions=[exclusion for part in parts for exclusion in part.exclusions],
    )
    result = report(
        cases,
        labels,
        rows,
        builds,
        refusal_set=refusal_digest,
        refusal_collisions=collisions(training, refusal_states),
    )
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "builds.json").write_text(
        json.dumps([b.model_dump() for b in builds], indent=2) + "\n", "utf-8"
    )
    for name, items in (("labels", labels), ("decisions", rows)):
        (out / f"{name}.jsonl").write_text(
            "".join(item.model_dump_json() + "\n" for item in items), "utf-8"
        )
    observed = [
        json.dumps({"index": case.index, "state": state.model_dump(mode="json")})
        for part in parts
        for case, state in zip(part.cases, part.states, strict=True)
    ]
    (out / "states.jsonl.gz").write_bytes(
        gzip.compress("".join(line + "\n" for line in observed).encode("utf-8"), mtime=0)
    )
    (out / "report.json").write_text(result.model_dump_json(indent=2) + "\n", "utf-8")
    (out / "summary.txt").write_text(text(result), "utf-8")
    return result


def _interval(estimate: rp.Estimate) -> str:
    if estimate.statistic is None:
        return "undefined"
    if estimate.interval is None:
        return f"{estimate.statistic:+.3f} [no interval]"
    return (
        f"{estimate.statistic:+.3f} [{estimate.interval.low:+.3f}, {estimate.interval.high:+.3f}]"
    )


def text(result: StudyReport) -> str:
    found = result.counts

    def rate(value: float | None) -> str:
        return "undefined" if value is None else f"{value:.3f}"

    lines = [
        "Study 2: refusal over a population of builds (refusal-population)",
        f"cases: {found.inexpressible} inexpressible, {found.clean} clean, {found.other} other, "
        f"from {found.repositories_with_a_case} repositories",
        f"valid builds: {result.valid_builds['0']} in configuration 0, "
        f"{result.valid_builds['R']} in configuration R",
        f"refusal set {result.refusal_set[:12]}; {result.refusal_collisions} of its states "
        f"repeat a training state's features",
        f"fire rate on inexpressible conflicts: Control-0 {rate(result.control_zero_fire_rate)}, "
        f"Control-R {rate(result.control_refusal_fire_rate)}",
    ]
    lines += [f"underpowered: {reason}" for reason in result.underpowered_because]
    hyp = result.hypotheses
    lines += [
        f"H1 f(Control-R) - f(R's builds): {_interval(hyp.h1)}",
        f"H2 f(Control-0) - f(0's builds): {_interval(hyp.h2)}",
        f"H3 f(0) - f(R): {_interval(hyp.h3)}",
        f"H4 right(R) - right(0) on clean cases: {_interval(hyp.h4)} (margin -{rp.H4_MARGIN})",
    ]
    for name, figures in result.spread.items():
        lines.append(
            f"spread of f in configuration {name}: mean {figures['mean']:.3f}, SD "
            f"{figures['sd']:.3f}, range {figures['min']:.3f}-{figures['max']:.3f}, IQR "
            f"{figures['iqr']:.3f}"
        )
    for build in result.builds:
        lines.append(
            f"build {build.configuration}{build.order}: f {rate(build.fire_rate)}, clean right "
            f"{rate(build.clean_right_rate)}, margin over its control "
            f"{_interval(build.against_control)}{' (beats it)' if build.beats_control else ''}"
        )
    lines += [f"rule {decision.rule}: {decision.outcome}" for decision in result.decisions]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.refusal_study")
    commands = parser.add_subparsers(dest="command", required=True)
    mining = commands.add_parser("mine-refusals", help="mine and freeze the refusal set (§3.3)")
    mining.add_argument("--out", type=Path, required=True)
    evaluation = commands.add_parser(
        "evaluate", help="mine list E, decide every case, estimate and decide (§3.4, §6-§9)"
    )
    evaluation.add_argument("--refusal-set", type=Path, required=True, metavar="DIR")
    evaluation.add_argument(
        "--zero",
        type=Path,
        nargs="+",
        required=True,
        metavar="LIBRARY",
        help="configuration 0's two-sided libraries",
    )
    evaluation.add_argument(
        "--refusal",
        type=Path,
        nargs="+",
        required=True,
        metavar="LIBRARY",
        help="configuration R's two-sided libraries",
    )
    evaluation.add_argument(
        "--out", type=Path, default=None, help="default: results/refusal-population-<today>"
    )
    args = parser.parse_args(argv)
    if args.command == "mine-refusals":
        refusals = mine_refusal_set(args.out)
        print(f"{len(refusals.cases)} inexpressible conflicts frozen in {args.out}")
        return 0
    out = args.out or REPOSITORY / f"results/refusal-population-{date.today().isoformat()}"
    print(text(evaluate(out, args.refusal_set, args.zero, args.refusal)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
