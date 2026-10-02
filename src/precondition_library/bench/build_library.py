"""Build the one frozen library every arm dispatches against (issue #4, ADR-0009).

Issue #4's central item: "a single library is compiled offline exactly once and
committed; every arm dispatches against that one artifact." Until now each arm grew its
own library online (`library-{arm}`), so an arm-2-versus-arm-3 difference could come
from different libraries rather than from different dispatch functions.

**Built from the admit set, and neutral between the arms.** Every `(fault, seed)` in
the admit set (`bench.splits.SMOKE_SEEDS`, spec §7) is solved by the agent and its
solution compiled and gated by the same `admit` the online runner uses. Each seed runs
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
compiled program is gated a second time with `AdmissionGate.POSITIVE_ONLY` into another
root, so the 2x2's two libraries come from one compile. Each root gets a `build.json`
naming its gate; the runner reads it to label rows.

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
from .ledger import Arm, append, transcripts_path
from .run import MANIFEST, _require_measurable, run_episode
from .splits import SMOKE_SEEDS, occurrence_roles

_BUILD_ARM = Arm.PRECONDITION
"""The arm named on build rows. Against an empty library both dispatch arms fall back to
solving on every episode, so the choice changes nothing but the label."""


class BuiltProgram(BaseModel):
    """One program the build produced, and whether it may be dispatched."""

    fault: str
    seed: int
    program_id: str
    admitted: bool


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
    seeds: tuple[int, ...] = SMOKE_SEEDS,
    positive_only_root: Path | None = None,
) -> BuildReport:
    """Solve, compile and gate every `(fault, seed)` into one frozen library at `root`.

    `root` must hold no program yet: a frozen library is built once, and adding to an
    existing one would make its contents depend on what was there before. Other files
    are left alone, so the committed `library/` -- whose README documents the
    directory -- can be the root. The build rows go to `ledger`, which must differ
    from the comparison's.

    `positive_only_root` builds the 2x2's second library in the same pass (ADR-0010):
    each compiled program is gated a second time with `AdmissionGate.POSITIVE_ONLY` and
    stored there. **Compiled once, gated twice**, so the two libraries hold the same
    programs and differ only in which the gate admitted -- two compiles would let a
    model's run-to-run variation into the admission factor.
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
    for fault in faults:
        roles = occurrence_roles(list(seeds), fault)
        for occurrence, seed in enumerate(seeds, start=1):
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
                        )
                    )
                    if positive_only_root is not None:
                        ungated.append(
                            _gate_positive_only(program, fault, seed, positive_only_root)
                        )

    _write_manifest(root, AdmissionGate.TWO_SIDED, faults, seeds)
    second: BuildReport | None = None
    if positive_only_root is not None:
        _write_manifest(positive_only_root, AdmissionGate.POSITIVE_ONLY, faults, seeds)
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


def _gate_positive_only(program: Program, fault: str, seed: int, root: Path) -> BuiltProgram:
    """Store the compiled program as a candidate in `root` and gate it positive-only.

    The candidate is the compiled program itself -- the two-sided gate only ever changed
    its status -- so resetting the status recovers exactly what the compile produced.
    """
    candidate = program.model_copy(update={"status": ProgramStatus.CANDIDATE})
    library = Library(root)
    library.add(candidate)
    admitted, _ = admit(candidate, fault, seeds=[seed], gate=AdmissionGate.POSITIVE_ONLY)
    if admitted:
        library.set_status(
            candidate.id, ProgramStatus.ADMITTED, episode_id=candidate.provenance.episode_id
        )
    return BuiltProgram(fault=fault, seed=seed, program_id=candidate.id, admitted=admitted)


def _write_manifest(
    root: Path, gate: AdmissionGate, faults: list[str], seeds: tuple[int, ...]
) -> None:
    manifest = {"admission_gate": gate.value, "faults": faults, "seeds": list(seeds)}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
