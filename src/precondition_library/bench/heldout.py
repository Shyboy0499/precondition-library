"""The held-out stage: does arm 3's zero mis-fire rate survive states no library saw? (issue #263)

The primary metric is measured on states the fault injectors build, and admission tests every
compiled program's preconditions against states from the same injectors and the same state
grid. So `0 of 563` is a statement about **this generator**: it shows the two-sided gate fits
the states the generators produce, not that preconditions carry to states they never produced.

This module is the second half of that sentence, and nothing else. It builds the held-out plan
block (`bench.splits.HELD_OUT_SEEDS`), where each state draws a path set no shipped seed draws
(`tasks.faults.dirty_tree.paths_for_seed`), dispatches the **committed** frozen library through
its own matchers on real sandboxes, and reports the same primary metric as Figure 1 -- mismatch
at matched coverage, one regime, with the power statement. No model call, no rebuild: the
library is opened read-only and its digest is compared before and after.

**What this stage may not say.** Two limits are structural, and both are registered in
ADR-0033 rather than decided here:

* **No held-out floor.** Spec section 7 item 11 measures arm 2's strict top-1 on the `TUNE_SEEDS`
  against the eval library, which is a statement about the shipped states; it does not transfer
  to states no library saw. This stage therefore reports the comparison and refuses the win
  wording instead of borrowing the shipped floor's verdict (`wording` in the summary says so).
* **A smaller set than Figure 1.** The held-out block is 40 seeds, one positive environment
  each, which makes it a pilot rather than a powered comparison: arm 3's fire count is well
  below the 187 the primary result rests on, so the smallest detectable difference the power
  statement computes is printed beside the comparison and nothing below it may be read -- an
  interval that spans it is "no difference detected at this N", not a null result. The reading is
  at the **distinct instances** the block builds, not at the seed or pair count: arm 3 is
  request-blind, so the requests crossed with one environment are one decision.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import ProgramStatus
from ..runtime.probes import evaluate_preconditions
from ..similarity import Similarity
from ..tasks.faults import FAULTS
from .coverage import PairOutcome
from .library_pairs import LibraryPairOutcomes, library_pair_outcomes
from .primary import (
    CONSERVATIVE_BASE_RATE,
    PrimaryReport,
    primary_report,
    summary,
    write_primary_report,
)
from .rescore import scorer
from .splits import HELD_OUT_SEEDS

HELD_OUT_FAULTS: tuple[str, ...] = ("dirty_tree",)
"""The faults this stage measures: the ones whose injector declares a held-out axis.

`tests/test_heldout_states.py` pins each name here against a declared axis, so a fault added
to this tuple without one fails rather than silently measuring the shipped states again."""

WORDING_LIMIT = (
    "no held-out floor is measured, so this stage may not say precondition dispatch beats text "
    "similarity; it reports the held-out coverage, the mis-fire counts and the comparison"
)


class WrongFire(BaseModel):
    """One fire the pair did not accept -- the evidence a mis-fire claim rests on."""

    environment: str
    correct_variant: str | None
    acceptable_variants: tuple[str, ...]
    fired_variant: str
    task_text: str


class HeldOutSummary(BaseModel):
    """The stage's record: what was measured, from which library, and what may be said."""

    source: str
    """The run directory the frozen library came from (or the library root, if free-standing)."""
    library_root: str
    library_hash_before: str
    library_hash_after: str
    scorer: dict[str, str]
    faults: list[str]
    seeds: list[int]
    distinct_instances: dict[str, int]
    """Per fault, the distinct **instances** the seeds build (`FaultSpec.instance_for_seed`).

    The number an independence claim is read at (ADR-0005 decision 4), which is not the seed
    count: several seeds can draw one instance, and the pairs crossed with a single
    environment are one decision for a request-blind arm 3, so they are not extra
    observations."""
    pairs: int
    programs: int
    admitted: int
    arm3_fires: int
    arm3_wrong: int
    arm2_at_matched: str
    smallest_detectable_difference: float | None
    wording: str
    figure: str
    wrong_fires: list[WrongFire]
    artifacts: dict[str, str] = {}


def _distinct_instances(faults: Sequence[str], seeds: Sequence[int]) -> dict[str, int]:
    """How many distinct instances each fault's seeds build, from the injectors' own draw.

    Computed from `FaultSpec.instance_for_seed`, the same identity `bench.splits` keys an
    occurrence's role on, so the count a reader is given and the one the plan would use
    cannot disagree.
    """
    return {
        fault: len({FAULTS[fault].instance_for_seed(seed) for seed in seeds}) for fault in faults
    }


def _wrong_fires(outcomes: LibraryPairOutcomes, arm3: Sequence[PairOutcome]) -> list[WrongFire]:
    """Arm 3's fires that the pair did not accept, with the pair they happened on."""
    found: list[WrongFire] = []
    for pair, outcome in zip(outcomes.pairs, arm3, strict=True):
        if outcome.fired_variant is None or outcome.decided_correctly:
            continue
        found.append(
            WrongFire(
                environment=pair.environment,
                correct_variant=outcome.correct_variant,
                acceptable_variants=outcome.acceptable_variants,
                fired_variant=outcome.fired_variant,
                task_text=pair.pair.task_text,
            )
        )
    return found


def _matched_text(report: PrimaryReport) -> str:
    """The matched-coverage sentence, or why there is none."""
    if report.vacuous is not None:
        return f"no comparison: {report.vacuous}"
    if report.matched is None:
        return "no comparison: arm 2 fired on no pair at any threshold"
    matched = report.matched
    difference = (
        "undefined"
        if matched.mismatch_difference is None
        else f"{matched.mismatch_difference:+.4f}"
    )
    return (
        f"arm 2 (threshold {matched.arm2.threshold}) mismatches "
        f"{matched.arm2.mismatch.numerator}/{matched.arm2.mismatch.denominator} at arm 3's "
        f"coverage, coverage gap {matched.coverage_gap:+.3f}, mismatch difference (arm 2 - "
        f"arm 3) {difference}"
    )


def run_held_out(
    library_root: Path,
    out: Path,
    *,
    similarity: Similarity,
    scorer_id: dict[str, str],
    source: str,
    faults: Sequence[str] = HELD_OUT_FAULTS,
    seeds: Sequence[int] = HELD_OUT_SEEDS,
    plot: bool = True,
) -> HeldOutSummary:
    """Measure the held-out block against the frozen library at `library_root`.

    `out` must not exist: like a live run and a rescore, the stage writes a fresh directory, so
    one scorer's figures cannot be mixed with another's. The library is read, never written,
    and the digest is compared before and after to prove it -- a `library_hash` printed beside
    a figure that moved the library it measured would be worthless.
    """
    if out.exists():
        raise ValueError(f"{out} already exists; the held-out stage writes a fresh directory")
    unknown = [fault for fault in faults if fault not in FAULTS]
    if unknown:
        raise ValueError(f"unknown faults {unknown}; known: {sorted(FAULTS)}")
    if not seeds:
        raise ValueError("no seeds, so no pairs")

    library = Library(
        library_root, similarity=similarity, evaluate_preconditions=evaluate_preconditions
    )
    programs = library.load_all()
    if not programs:
        raise ValueError(f"{library_root} holds no program; there is nothing to measure")
    before = library.library_hash()

    outcomes = library_pair_outcomes(library, list(faults), list(seeds))
    report = primary_report(outcomes.arm2, outcomes.arm3, baselines=outcomes.baselines())
    out.mkdir(parents=True)
    write_primary_report(report, out / "primary", plot=plot)

    after = library.library_hash()
    if before != after:
        raise RuntimeError(
            f"the held-out stage changed the library it measured ({before} -> {after}); a "
            "figure computed from a library that moved is not a figure"
        )

    wrong = _wrong_fires(outcomes, outcomes.arm3)
    result = HeldOutSummary(
        source=source,
        library_root=str(library_root),
        library_hash_before=before,
        library_hash_after=after,
        scorer=scorer_id,
        faults=list(faults),
        seeds=list(seeds),
        distinct_instances=_distinct_instances(faults, seeds),
        pairs=len(outcomes.pairs),
        programs=len(programs),
        admitted=sum(program.status is ProgramStatus.ADMITTED for program in programs),
        arm3_fires=report.arm3.coverage.numerator,
        arm3_wrong=report.arm3.mismatch.numerator,
        arm2_at_matched=_matched_text(report),
        smallest_detectable_difference=(
            report.power.at_conservative_rate if report.power is not None else None
        ),
        wording=WORDING_LIMIT,
        figure=summary(report),
        wrong_fires=wrong,
        artifacts={"primary": "primary"},
    )
    (out / "heldout.json").write_text(
        json.dumps(
            {
                **scorer_id,
                "source": source,
                "library_root": str(library_root),
                "library_hash": before,
                "faults": list(faults),
                "seeds": {"first": min(seeds), "last": max(seeds), "count": len(seeds)},
                "pairs": result.pairs,
                "arm3": {"fires": result.arm3_fires, "wrong": result.arm3_wrong},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out / "wrong_fires.jsonl").open("w", encoding="utf-8") as handle:
        for fire in wrong:
            handle.write(fire.model_dump_json() + "\n")
    (out / "summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(text(result), encoding="utf-8")
    return result


def text(result: HeldOutSummary) -> str:
    """The stage's own summary: what it measured, and the two sentences it may not write."""
    detectable = (
        "undefined"
        if result.smallest_detectable_difference is None
        else f"{result.smallest_detectable_difference:.3f}"
    )
    lines = [
        f"Held-out stage (issue #263): {result.pairs} labelled pairs, faults "
        f"{', '.join(result.faults)}, seeds {min(result.seeds)}-{max(result.seeds)} "
        f"({len(result.seeds)})",
        "  distinct instances built: "
        + ", ".join(
            f"{fault} {count}" for fault, count in sorted(result.distinct_instances.items())
        )
        + " -- the number an independence claim is read at, not the seed count",
        f"  library {result.library_root} ({result.admitted} admitted of {result.programs} "
        f"programs), hash {result.library_hash_before}",
        f"  arm 2 scorer: {result.scorer.get('scorer')}"
        + (
            f" {result.scorer.get('model_id')}@{result.scorer.get('revision', '')[:8]}"
            if result.scorer.get("model_id")
            else ""
        ),
        f"  arm 3: fires {result.arm3_fires}, wrong {result.arm3_wrong}",
        f"  {result.arm2_at_matched}",
        f"  smallest detectable mismatch difference at a {CONSERVATIVE_BASE_RATE:.0%} base rate "
        f"with these fire counts: {detectable}",
        f"  wording: {result.wording}",
    ]
    if result.wrong_fires:
        lines.append(f"  wrong fires ({len(result.wrong_fires)}), each naming its pair:")
        for fire in result.wrong_fires:
            lines.append(
                f"    {fire.environment}: fired {fire.fired_variant}, pair accepts "
                f"{fire.acceptable_variants or fire.correct_variant!r} -- {fire.task_text!r}"
            )
    lines.append("")
    lines.append(result.figure.rstrip("\n"))
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.heldout",
        description=(
            "Measure the primary metric on held-out states with a committed frozen library "
            "(issue #263). No model call."
        ),
    )
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="a finished run directory holding library-two-sided/ (the frozen library)",
    )
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    parser.add_argument(
        "--scorer", choices=("lexical", "embedding", "cross-encoder"), default="lexical"
    )
    parser.add_argument(
        "--faults",
        nargs="+",
        default=list(HELD_OUT_FAULTS),
        help="the faults whose held-out axis to measure",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=list(HELD_OUT_SEEDS),
        help="the held-out block to measure (default: the registered one)",
    )
    parser.add_argument("--no-plot", action="store_true", help="skip figure1.png")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    similarity, identity = scorer(args.scorer)
    library_root = args.run / "library-two-sided"
    result = run_held_out(
        library_root,
        args.out,
        similarity=similarity,
        scorer_id=identity,
        source=str(args.run),
        faults=tuple(args.faults),
        seeds=tuple(args.seeds),
        plot=not args.no_plot,
    )
    print(text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
