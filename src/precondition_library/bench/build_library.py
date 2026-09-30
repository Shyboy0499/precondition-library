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

Building needs a model: the solves and compiles are LLM calls. This module takes the
`provider` as the runner does and reads no environment, so it runs wherever a key is
configured; `tests/test_build_library.py` exercises it with a scripted provider.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import ProgramStatus
from ..provider import Provider
from ..runtime.probes import evaluate_preconditions
from .ledger import Arm, append
from .run import _require_measurable, run_episode
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
    """What the build put in the frozen library, and the hash every arm will record."""

    root: Path
    ledger: Path
    programs: list[BuiltProgram]
    library_hash: str

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
) -> BuildReport:
    """Solve, compile and gate every `(fault, seed)` into one frozen library at `root`.

    `root` must hold no program yet: a frozen library is built once, and adding to an
    existing one would make its contents depend on what was there before. Other files
    are left alone, so the committed `library/` -- whose README documents the
    directory -- can be the root. The build rows go to `ledger`, which must differ
    from the comparison's.
    """
    _require_measurable(faults)
    existing = Library(root).load_all()
    if existing:
        raise ValueError(
            f"{root} already holds {len(existing)} program(s); a frozen library is built once "
            f"into a directory with none, so its contents are exactly this build's"
        )
    root.mkdir(parents=True, exist_ok=True)

    built: list[BuiltProgram] = []
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

    return BuildReport(
        root=root, ledger=ledger, programs=built, library_hash=Library(root).library_hash()
    )
