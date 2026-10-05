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
    """
    _require_measurable(faults)
    for target in (root, positive_only_root):
        if target is None:
            continue
        existing = Library(target).load_all()
        if existing:
            raise ValueError(
                f"{target} already holds {len(existing)} program(s); a frozen library is built "
                f"once into a directory with none, so its contents are exactly this build's"
            )
        target.mkdir(parents=True, exist_ok=True)

    built: list[BuiltProgram] = []
    ungated: list[BuiltProgram] = []
    plan = _episode_plan(faults, seeds)
    for fault in faults:
        episodes = plan[fault]
        roles = occurrence_roles([seed for seed, _, _ in episodes], fault)
        for occurrence, (seed, resolution, request) in enumerate(episodes, start=1):
            with tempfile.TemporaryDirectory(prefix="build-library-") as scratch:
                library = Library(Path(scratch), evaluate_preconditions=evaluate_preconditions)
                record = run_episode(
                    _BUILD_ARM,
                    fault,
                    seed,
                    occurrence,
                    role=roles[occurrence - 1],
                    provider=provider,
                    library=library,
                    model=model,
                    transcript_log=transcripts_path(ledger),
                    request=request,
                )
                append(ledger, record)
                for program in library.load_all():
                    shutil.copytree(Path(scratch) / program.id, root / program.id)
                    built.append(
                        BuiltProgram(
                            fault=fault,
                            seed=seed,
                            program_id=program.id,
                            admitted=program.status is ProgramStatus.ADMITTED,
                            resolution=resolution,
                        )
                    )
                    if positive_only_root is not None:
                        first = library.first_compile(program.id)
                        ungated.append(
                            _gate_positive_only(first, fault, seed, positive_only_root).model_copy(
                                update={"resolution": resolution}
                            )
                        )

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


def _episode_plan(faults: list[str], seeds: tuple[int, ...] | None) -> dict[str, list[_Episode]]:
    """Each fault's build episodes: the admit set's (ADR-0032), or `seeds` with the fault's
    own requests."""
    if seeds is not None:
        return {fault: [(seed, None, None) for seed in seeds] for fault in faults}
    missing = sorted(set(faults) - set(ADMIT_SET))
    if missing:
        raise ValueError(f"the admit set has no episodes for {missing}; pass `seeds` instead")
    return {
        fault: [
            (episode.seed, episode.resolution, admit_request(fault, episode))
            for episode in ADMIT_SET[fault]
        ]
        for fault in faults
    }


def _write_manifest(
    root: Path, gate: AdmissionGate, faults: list[str], plan: dict[str, list[_Episode]]
) -> None:
    """`build.json`: the gate, and per fault the episodes the build ran -- each seed with
    the resolution it asked for, or `null` when it used the fault's own request."""
    episodes = {
        fault: [{"seed": seed, "resolution": resolution} for seed, resolution, _ in plan[fault]]
        for fault in faults
    }
    manifest = {"admission_gate": gate.value, "faults": faults, "episodes": episodes}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
