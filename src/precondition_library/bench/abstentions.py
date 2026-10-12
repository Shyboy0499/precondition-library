"""Why arm 3 sits out: every positive pair it does not fire on, and which check stopped it.

Arm 3 fires on 187-189 of each committed library's 200 positive pairs and on none of the 200
fault-free negatives. The 11-13 positives it misses are where its coverage is lost, and Figure 1
reports only their count. This stage names each one and says why, which separates the two causes
a reader would act on differently:

* **no program** -- the library holds no admitted program for any resolution the state accepts,
  so nothing could have fired. That is a gap in what the build learned (ADR-0032's admit set).
* **checks refused** -- an admitted program for an acceptable resolution exists, and at least one
  of its preconditions did not hold on this state. That is a precondition stricter than the
  state needed, or a probe that misreads it, and the failing predicate is recorded with what it
  observed.

The pairs are the pair pass's own (`bench.library_pairs`): the same seeds, environments, labels
and `is_pair` rule, uninformed regime. Arm 3 accepts a program exactly as
`Library.match_preconditions` does -- admitted, and `evaluate_preconditions(program, env).ok` --
and the evaluation is kept per program so the reason can be read. No model call is made, and the
library is read, never written.

Usage: `python -m precondition_library.bench.abstentions --run RUN_DIR --out DIR`.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import GroundTruthResult, Program, ProgramStatus
from ..runtime.probes import evaluate_preconditions
from ..signatures import StateFingerprint
from ..tasks.faults import build_sandbox
from .library_pairs import FAULT_FREE, _measured_intents, is_pair
from .live import LivePlan
from .pairs import label

NO_PROGRAM = "no program"
CHECKS_REFUSED = "checks refused"


class FailedCheck(BaseModel):
    """One precondition that did not hold, with what the probe saw instead."""

    name: str
    observed: str
    refused: bool


class CandidateVerdict(BaseModel):
    """An admitted program for a resolution this state accepts, and why it did not fire."""

    program_id: str
    variant: str | None
    failed: list[FailedCheck]


class Abstention(BaseModel):
    """One positive pair arm 3 did not fire on."""

    seed: int
    environment: str
    intent: str
    correct_variant: str
    acceptable_variants: tuple[str, ...]
    cause: str
    """`NO_PROGRAM` or `CHECKS_REFUSED`."""
    candidates: list[CandidateVerdict]
    """Every admitted program whose variant the state accepts: empty exactly when the cause is
    `NO_PROGRAM`."""
    state: StateFingerprint


class AbstentionReport(BaseModel):
    library_hash: str
    source: str
    positives: int
    negatives: int
    arm3_fires: int
    arm3_fires_on_negatives: int
    abstentions: list[Abstention]

    @property
    def by_cause(self) -> dict[str, int]:
        return dict(Counter(item.cause for item in self.abstentions))


def _failed(result: GroundTruthResult) -> list[FailedCheck]:
    return [
        FailedCheck(name=item.name, observed=item.observed, refused=item.refused)
        for item in result.predicates
        if not item.ok
    ]


def abstentions(
    library: Library, faults: Sequence[str], seeds: Sequence[int], *, source: str = ""
) -> AbstentionReport:
    """Every positive pair over `seeds` that arm 3 does not fire on, with its cause.

    Also counts what it walked -- positives, negatives, arm 3's fires and any fire on a negative --
    so the report can be checked against the run's own Figure 1 rather than taken on trust.
    """
    evaluate = library.evaluate_preconditions
    if evaluate is None:
        raise ValueError(
            "arm 3 needs a predicate evaluator; pass Library(root, evaluate_preconditions=...)"
        )
    if not seeds:
        raise ValueError("no seeds, so no pairs")
    intents = _measured_intents(faults)
    admitted: list[Program] = [p for p in library.load_all() if p.status is ProgramStatus.ADMITTED]

    positives = negatives = fires = fires_on_negatives = 0
    found: list[Abstention] = []
    for seed in seeds:
        for environment, injected in [(FAULT_FREE, []), *((f, [f]) for f in faults)]:
            box = build_sandbox(seed, injected)
            try:
                verdicts = {program.id: evaluate(program, box) for program in admitted}
                state = StateFingerprint.observe(box)
            finally:
                box.destroy()
            accepted = any(verdict.ok for verdict in verdicts.values())
            for intent in intents:
                pair = label(intent, seed, state, uninformed=True)
                if not is_pair(environment, intent, pair):
                    continue
                if pair.correct_variant is None:
                    negatives += 1
                    fires_on_negatives += accepted
                    continue
                positives += 1
                if accepted:
                    fires += 1
                    continue
                acceptable = set(pair.acceptable_variants) | {pair.correct_variant}
                candidates = [
                    CandidateVerdict(
                        program_id=program.id,
                        variant=program.variant,
                        failed=_failed(verdicts[program.id]),
                    )
                    for program in admitted
                    if program.variant in acceptable and program.provenance.fault == intent.fault
                ]
                found.append(
                    Abstention(
                        seed=seed,
                        environment=environment,
                        intent=intent.name,
                        correct_variant=pair.correct_variant,
                        acceptable_variants=pair.acceptable_variants,
                        cause=CHECKS_REFUSED if candidates else NO_PROGRAM,
                        candidates=candidates,
                        state=state,
                    )
                )
    return AbstentionReport(
        library_hash=library.library_hash(),
        source=source,
        positives=positives,
        negatives=negatives,
        arm3_fires=fires + fires_on_negatives,
        arm3_fires_on_negatives=fires_on_negatives,
        abstentions=found,
    )


def text(report: AbstentionReport) -> str:
    lines = [
        f"Arm 3's abstentions on {report.source or 'the library'} "
        f"(library {report.library_hash[:12]})",
        f"  pairs: {report.positives} positive, {report.negatives} negative",
        f"  arm 3 fires: {report.arm3_fires} ({report.arm3_fires_on_negatives} on negatives)",
        f"  positives arm 3 sat out: {len(report.abstentions)}",
    ]
    for cause, count in sorted(report.by_cause.items()):
        lines.append(f"    {cause}: {count}")
    for item in report.abstentions:
        lines.append(
            f"  - seed {item.seed}, {item.environment} state, intent {item.intent}: "
            f"needs {item.correct_variant} (accepts {', '.join(item.acceptable_variants)}) "
            f"-- {item.cause}"
        )
        for candidate in item.candidates:
            for check in candidate.failed:
                kind = "refused" if check.refused else "did not hold"
                observed = check.observed.strip().replace("\n", " ")[:120]
                lines.append(
                    f"      {candidate.program_id} ({candidate.variant}): {check.name} {kind}; "
                    f"observed: {observed or '(nothing)'}"
                )
    return "\n".join(lines) + "\n"


def write(report: AbstentionReport, out: Path) -> None:
    """`abstentions.jsonl` (one row per abstention), `abstentions.json` and `summary.txt`."""
    if out.exists():
        raise ValueError(f"{out} already exists; the stage writes into a fresh directory")
    out.mkdir(parents=True)
    with (out / "abstentions.jsonl").open("w", encoding="utf-8") as handle:
        for item in report.abstentions:
            handle.write(item.model_dump_json() + "\n")
    summary = report.model_dump(mode="json", exclude={"abstentions"})
    summary["abstained"] = len(report.abstentions)
    summary["by_cause"] = report.by_cause
    (out / "abstentions.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "summary.txt").write_text(text(report), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.abstentions",
        description="Name every positive pair arm 3 sits out, and the check that stopped it.",
    )
    parser.add_argument("--run", type=Path, required=True, help="a finished live run directory")
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    recorded = json.loads((args.run / "plan.json").read_text(encoding="utf-8"))
    plan = LivePlan.model_validate(recorded["plan"])
    library = Library(args.run / "library-two-sided", evaluate_preconditions=evaluate_preconditions)
    report = abstentions(library, list(plan.faults), list(plan.pair_seeds), source=str(args.run))
    write(report, args.out)
    print(text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
