"""Build the one frozen library every arm dispatches against (issue #4, ADR-0009).

Issue #4's central item: "a single library is compiled offline exactly once and
committed; every arm dispatches against that one artifact." Until now each arm grew its
own library online (`library-{arm}`), so an arm-2-versus-arm-3 difference could come
from different libraries rather than from different dispatch functions.

**Built from the admit set, and neutral between the arms.** Every episode of the admit
set (`bench.admit_set.ADMIT_SET`, ADR-0032: one per declared resolution, its request
asking for that resolution) is solved by the agent and its solution compiled and gated
by the same `admit` the online runner uses. A caller may pass `seeds` instead, which
runs those seeds for every fault with the fault's own requests, as builds did before. Each seed runs
against its **own empty scratch library**, so nothing is ever dispatched during the
build: which programs end up in the artifact cannot depend on either arm's dispatch
decisions. An admitted program's whole directory -- `program.yaml` and the
`history.jsonl` that records its admission -- is then copied into the frozen root, and
a program that failed the gate is copied too, as the `candidate` it stayed: a rejected
program is data (`library/README.md` rule 1).

The build's episodes are ordinary ledger rows, written to their own ledger so the cost
of building is recorded and never mixed into the comparison's rows. Their `arm` is
`precondition` only because an arm has to be named: against an empty library both
dispatch arms fall straight back to solving, so the two are identical here.

**The admission factor's second library** (ADR-0010). With `positive_only_root`, every
episode's first compile is gated a second time with `AdmissionGate.POSITIVE_ONLY` into
another root, so the 2x2's two libraries come from one compile. A program the two-sided
gate refused may be revised once (ADR-0030); the revision is the two-sided gate's
feedback, so it stays in the two-sided library and the positive-only one keeps the first
compile. Each root gets a `build.json` naming its gate; the runner reads it to label
rows.

**Resuming an interrupted build.** A live build is two hours of model calls, and the
fifth and ninth live runs' containers restarted part-way through. Each finished episode
is therefore committed to `<ledger stem>.progress.jsonl` -- its programs as built, once
they are in both roots -- and `resume=True` skips every committed episode, re-reading
its programs from there, so the fallback seeds and the report come out as one
uninterrupted build would make them. An episode cut off mid-way left no commit, so it
runs again; the programs it copied, if any, are removed first. Its ledger row stays if
it was written: the row is what the attempt spent.

Building needs a model: the solves and compiles are LLM calls. This module takes the
`provider` as the runner does and reads no environment, so it runs wherever a key is
configured; `tests/test_build_library.py` exercises it with a scripted provider.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel

from ..agents.compile import AdmissionGate, admit
from ..library import Library
from ..program import Program, ProgramStatus
from ..provider import Provider
from ..runtime.probes import evaluate_preconditions
from .admit_set import ADMIT_SET, admit_request
from .ledger import Arm, append, transcripts_path
from .run import MANIFEST, _require_measurable, run_episode
from .splits import occurrence_roles

_BUILD_ARM = Arm.PRECONDITION
"""The arm named on build rows. Against an empty library both dispatch arms fall back to
solving on every episode, so the choice changes nothing but the label."""


class BuiltProgram(BaseModel):
    """One program the build produced, and whether it may be dispatched."""

    fault: str
    seed: int
    program_id: str
    admitted: bool
    resolution: str | None = None
    """The resolution the admit-set episode asked for (ADR-0032); `None` for `seeds`."""


class BuildReport(BaseModel):
    """What the build put in one frozen library, and the hash every arm will record."""

    root: Path
    ledger: Path
    gate: AdmissionGate
    programs: list[BuiltProgram]
    library_hash: str
    positive_only: BuildReport | None = None
    """The same compiled programs gated positive-only, when a second root was asked for:
    the 2x2's ungated library (ADR-0010)."""

    @property
    def admitted(self) -> int:
        return sum(program.admitted for program in self.programs)


def build_library(
    *,
    faults: list[str],
    root: Path,
    ledger: Path,
    provider: Provider,
    model: str,
    seeds: tuple[int, ...] | None = None,
    positive_only_root: Path | None = None,
    resume: bool = False,
) -> BuildReport:
    """Solve, compile and gate every `(fault, seed)` into one frozen library at `root`.

    `root` must hold no program yet: a frozen library is built once, and adding to an
    existing one would make its contents depend on what was there before. Other files
    are left alone, so the committed `library/` -- whose README documents the
    directory -- can be the root. The build rows go to `ledger`, which must differ
    from the comparison's.

    `positive_only_root` builds the 2x2's second library in the same pass (ADR-0010):
    each episode's first compile is gated a second time with `AdmissionGate.POSITIVE_ONLY`
    and stored there. **Compiled once, gated twice**, so the two libraries hold the same
    first programs -- two compiles would let a model's run-to-run variation into the
    admission factor. Where the two-sided gate refused one and its revision was stored
    (ADR-0030), the two-sided library holds the revision: telling the compiler why is
    part of what that gate does, and the positive-only gate has no negative side to
    tell it anything.

    `resume` continues a build that was interrupted, from the episodes its progress file
    committed; see the module docstring.
    """
    _require_measurable(faults)
    progress = progress_path(ledger)
    committed = _read_progress(progress) if resume else {}
    if not resume and progress.exists():
        raise ValueError(f"{progress} records an earlier build; pass resume=True to continue it")
    for target, key in ((root, "programs"), (positive_only_root, "ungated")):
        if target is None:
            continue
        if resume:
            kept = {p["program_id"] for entry in committed.values() for p in entry[key]}
            _remove_uncommitted(target, kept)
        else:
            existing = Library(target).load_all()
            if existing:
                raise ValueError(
                    f"{target} already holds {len(existing)} program(s); a frozen library is "
                    f"built once into a directory with none, so its contents are exactly this "
                    f"build's"
                )
        target.mkdir(parents=True, exist_ok=True)

    built: list[BuiltProgram] = []
    ungated: list[BuiltProgram] = []
    plan = _episode_plan(faults, seeds)
    for fault in faults:
        run_seeds: list[int] = []
        for group in plan[fault]:
            # A resolution's seeds are tried in order until one admits a program (ADR-0032):
            # the fallback runs only when the episode before it admitted nothing.
            for seed, resolution, request in group:
                run_seeds.append(seed)
                occurrence = len(run_seeds)
                done = committed.get((fault, seed))
                if done is not None:
                    built.extend(BuiltProgram.model_validate(p) for p in done["programs"])
                    ungated.extend(BuiltProgram.model_validate(p) for p in done["ungated"])
                    if any(p["admitted"] for p in done["programs"]):
                        break
                    continue
                episode_built: list[BuiltProgram] = []
                episode_ungated: list[BuiltProgram] = []
                with tempfile.TemporaryDirectory(prefix="build-library-") as scratch:
                    library = Library(Path(scratch), evaluate_preconditions=evaluate_preconditions)
                    record = run_episode(
                        _BUILD_ARM,
                        fault,
                        seed,
                        occurrence,
                        role=occurrence_roles(run_seeds, fault)[-1],
                        provider=provider,
                        library=library,
                        model=model,
                        transcript_log=transcripts_path(ledger),
                        request=request,
                    )
                    append(ledger, record)
                    admitted_here = False
                    for program in library.load_all():
                        shutil.copytree(Path(scratch) / program.id, root / program.id)
                        admitted = program.status is ProgramStatus.ADMITTED
                        admitted_here = admitted_here or admitted
                        episode_built.append(
                            BuiltProgram(
                                fault=fault,
                                seed=seed,
                                program_id=program.id,
                                admitted=admitted,
                                resolution=resolution,
                            )
                        )
                        if positive_only_root is not None:
                            first = library.first_compile(program.id)
                            episode_ungated.append(
                                _gate_positive_only(
                                    first, fault, seed, positive_only_root
                                ).model_copy(update={"resolution": resolution})
                            )
                _commit(progress, fault, seed, episode_built, episode_ungated)
                built.extend(episode_built)
                ungated.extend(episode_ungated)
                if admitted_here:
                    break

    _write_manifest(root, AdmissionGate.TWO_SIDED, faults, plan)
    second: BuildReport | None = None
    if positive_only_root is not None:
        _write_manifest(positive_only_root, AdmissionGate.POSITIVE_ONLY, faults, plan)
        second = BuildReport(
            root=positive_only_root,
            ledger=ledger,
            gate=AdmissionGate.POSITIVE_ONLY,
            programs=ungated,
            library_hash=Library(positive_only_root).library_hash(),
        )
    return BuildReport(
        root=root,
        ledger=ledger,
        gate=AdmissionGate.TWO_SIDED,
        programs=built,
        library_hash=Library(root).library_hash(),
        positive_only=second,
    )


def progress_path(ledger: Path) -> Path:
    """Where a build commits each finished episode, beside its ledger."""
    return ledger.with_name(f"{ledger.stem}.progress.jsonl")


def _commit(
    progress: Path,
    fault: str,
    seed: int,
    programs: list[BuiltProgram],
    ungated: list[BuiltProgram],
) -> None:
    """Record that `(fault, seed)` finished, with what it put in each root."""
    entry = {
        "fault": fault,
        "seed": seed,
        "programs": [program.model_dump() for program in programs],
        "ungated": [program.model_dump() for program in ungated],
    }
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _read_progress(progress: Path) -> dict[tuple[str, int], dict]:
    """Each committed episode's entry, by `(fault, seed)`. A last line cut off by the
    interruption was never a commit, so it is ignored."""
    if not progress.is_file():
        return {}
    committed: dict[tuple[str, int], dict] = {}
    for line in progress.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        committed[(entry["fault"], entry["seed"])] = entry
    return committed


_PROGRAM_FILES = frozenset({"program.yaml", "history.jsonl"})


def _remove_uncommitted(root: Path, kept: set[str]) -> None:
    """Remove the program directories under `root` that no committed episode built: what
    an interrupted episode had copied. Anything that is not a program directory is left,
    and a directory holding other files is refused rather than deleted."""
    if not root.is_dir():
        return
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name in kept:
            continue
        names = {child.name for child in path.iterdir()}
        if not names <= _PROGRAM_FILES:
            raise ValueError(
                f"{path} is not a program this build committed, and holds {sorted(names)}; "
                "a resumed build removes only the program directories it wrote"
            )
        shutil.rmtree(path)


def _gate_positive_only(candidate: Program, fault: str, seed: int, root: Path) -> BuiltProgram:
    """Store the episode's first compile as a candidate in `root` and gate it positive-only."""
    library = Library(root)
    library.add(candidate)
    admitted, _ = admit(candidate, fault, seeds=[seed], gate=AdmissionGate.POSITIVE_ONLY)
    if admitted:
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    return BuiltProgram(fault=fault, seed=seed, program_id=candidate.id, admitted=admitted)


_Episode = tuple[int, str | None, str | None]
"""One build episode: its seed, the resolution it asks for, and its request (`None`
for the fault's own)."""

_Group = list[_Episode]
"""One resolution's episodes, tried in order until one admits a program."""


def _episode_plan(faults: list[str], seeds: tuple[int, ...] | None) -> dict[str, list[_Group]]:
    """Each fault's build episodes, grouped by resolution: the admit set's (ADR-0032), each
    resolution's seeds in order, or `seeds`, each its own group with the fault's own
    request."""
    if seeds is not None:
        return {fault: [[(seed, None, None)] for seed in seeds] for fault in faults}
    missing = sorted(set(faults) - set(ADMIT_SET))
    if missing:
        raise ValueError(f"the admit set has no episodes for {missing}; pass `seeds` instead")
    return {
        fault: [
            [
                (seed, episode.resolution, admit_request(fault, episode, seed))
                for seed in episode.seeds
            ]
            for episode in ADMIT_SET[fault]
        ]
        for fault in faults
    }


def _write_manifest(
    root: Path, gate: AdmissionGate, faults: list[str], plan: dict[str, list[_Group]]
) -> None:
    """`build.json`: the gate, and per fault the registered plan -- each resolution with
    the seeds it may try, in order, or `null` for a seed run with the fault's own request.
    Which of them ran is in the build ledger."""
    episodes = {
        fault: [
            {"resolution": group[0][1], "seeds": [seed for seed, _, _ in group]}
            for group in plan[fault]
        ]
        for fault in faults
    }
    manifest = {"admission_gate": gate.value, "faults": faults, "episodes": episodes}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
