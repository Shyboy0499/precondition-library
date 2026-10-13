"""What dispatch costs in probes when it stops at the first program that holds (issue #265).

Once no model is called, a dispatcher's remaining cost is the predicates it evaluates. Arm 3 as
implemented evaluates **every** admitted program's preconditions on every request, then fires the
most specific one that held. It need not: it can make the same decision lazily, evaluating programs
most-specific-first and stopping at the first that holds. The hybrid (`bench.hybrid`) can do the
same in **text** order, which is the case for retrieval -- it reaches the right program sooner --
and its top-`k` cap stops it sooner still, at the price of the fires it then never reaches.

This module prices all three from the hybrid stage's saved record (`pairs.jsonl`: each pair's
accepted set and complete text ranking) and the library, with no sandbox:

* **arm 3, every program** -- what the shipped matcher evaluates;
* **arm 3, lazy** -- specificity order (`Library.match_preconditions`' order), stopping at the
  first program that holds. Same decision as arm 3 on every pair, by construction;
* **lazy hybrid, k** -- text order, stopping at the first that holds or after `k` programs. Its
  decisions are `bench.hybrid.hybrid_decision`'s at no retrieval floor.

Cost is **predicates evaluated** -- `runtime.probes.evaluate_predicates` runs one probe per
predicate and never short-circuits inside a program -- and programs reached. A non-firing walk
pays for every program it reached, which is what a negative pair costs.

Usage: `python -m precondition_library.bench.probe_cost --hybrid DIR --library DIR --out FILE.csv`.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import Program, ProgramStatus
from .coverage import PairOutcome, operating_point
from .hybrid import KS, NO_FLOOR, hybrid_decision
from .library_pairs import LibraryPair


class Walk(BaseModel):
    """What one lazy walk over one pair fired, and what it evaluated to get there."""

    fired_variant: str | None
    programs: int
    predicates: int


def _walk(
    order: Sequence[str], accepted: set[str], variant: dict[str, str | None], cost: dict[str, int]
) -> Walk:
    reached = spent = 0
    for program_id in order:
        reached += 1
        spent += cost[program_id]
        if program_id in accepted:
            return Walk(fired_variant=variant[program_id], programs=reached, predicates=spent)
    return Walk(fired_variant=None, programs=reached, predicates=spent)


class CostRow(BaseModel):
    """One dispatcher's probe bill over the pairs, beside what it decided."""

    dispatcher: str
    k: int | None
    pairs: int
    fires: int
    wrong: int
    programs_per_pair: float
    predicates_per_pair: float
    saved_vs_every_program: float
    """`1 - predicates / arm 3's every-program predicates`, the share of probe work skipped."""


def _row(
    name: str, k: int | None, pairs: Sequence[LibraryPair], walks: Sequence[Walk], full: float
) -> CostRow:
    point = operating_point(
        [
            PairOutcome(
                correct_variant=pair.pair.correct_variant,
                acceptable_variants=pair.pair.acceptable_variants,
                fired_variant=walk.fired_variant,
                score=None,
                informed=pair.pair.informed,
            )
            for pair, walk in zip(pairs, walks, strict=True)
        ]
    )
    predicates = sum(walk.predicates for walk in walks) / len(walks)
    return CostRow(
        dispatcher=name,
        k=k,
        pairs=len(pairs),
        fires=point.coverage.numerator,
        wrong=point.mismatch.numerator,
        programs_per_pair=sum(walk.programs for walk in walks) / len(walks),
        predicates_per_pair=predicates,
        saved_vs_every_program=1.0 - predicates / full if full else 0.0,
    )


def cost_table(
    pairs: Sequence[LibraryPair], programs: Sequence[Program], ks: Sequence[int | None] = KS
) -> list[CostRow]:
    """Arm 3 evaluating every program, arm 3 lazy, then the lazy hybrid at each `k`.

    Raises when a lazy walk's decision disagrees with the one it stands for -- arm 3's for the lazy
    arm 3, `hybrid_decision`'s for the hybrid -- because a cheaper walk that decides differently
    is a different dispatcher, and pricing it as this one would be wrong.
    """
    if not pairs:
        raise ValueError("no pairs, so nothing to price")
    admitted = [program for program in programs if program.status is ProgramStatus.ADMITTED]
    cost = {program.id: len(program.preconditions) for program in admitted}
    variant = {program.id: program.variant for program in admitted}
    specific = [
        program.id for program in sorted(admitted, key=lambda p: (-len(p.preconditions), p.id))
    ]
    full = float(sum(cost.values()))

    every = [
        Walk(
            fired_variant=variant[pair.accepted[0]] if pair.accepted else None,
            programs=len(admitted),
            predicates=int(full),
        )
        for pair in pairs
    ]
    lazy3 = [_walk(specific, set(pair.accepted), variant, cost) for pair in pairs]
    for pair, walk, whole in zip(pairs, lazy3, every, strict=True):
        if walk.fired_variant != whole.fired_variant:
            raise RuntimeError(f"lazy arm 3 decided differently from arm 3 on {pair.pair}")
    rows = [
        _row("arm 3, every program", None, pairs, every, full),
        _row("arm 3, lazy (specificity order)", None, pairs, lazy3, full),
    ]
    for k in ks:
        walks = [
            _walk(
                [c.id for c in pair.ranked][: k if k is not None else None],
                set(pair.accepted),
                variant,
                cost,
            )
            for pair in pairs
        ]
        for pair, walk in zip(pairs, walks, strict=True):
            if walk.fired_variant != hybrid_decision(pair, k=k, threshold=NO_FLOOR):
                raise RuntimeError(
                    f"lazy hybrid decided differently from the hybrid on {pair.pair}"
                )
        rows.append(_row("lazy hybrid (text order)", k, pairs, walks, full))
    return rows


def read_pairs(path: Path) -> list[LibraryPair]:
    return [
        LibraryPair.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write(rows: Sequence[CostRow], out: Path) -> None:
    if out.exists():
        raise ValueError(f"{out} already exists; the stage writes a fresh file")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(CostRow.model_fields))
        for row in rows:
            writer.writerow(["all" if v is None and name == "k" else v for name, v in row])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.probe_cost",
        description="Price lazy dispatch in predicates evaluated, from a hybrid stage's record.",
    )
    parser.add_argument("--hybrid", type=Path, required=True, help="a hybrid stage's output dir")
    parser.add_argument("--library", type=Path, required=True, help="the library it measured")
    parser.add_argument("--out", type=Path, required=True, help="fresh CSV path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rows = cost_table(read_pairs(args.hybrid / "pairs.jsonl"), Library(args.library).load_all())
    write(rows, args.out)
    for row in rows:
        k = "" if row.k is None else f" k={row.k}"
        print(
            f"{row.dispatcher}{k}: fires {row.fires}/{row.pairs}, wrong {row.wrong}, "
            f"{row.programs_per_pair:.2f} programs and {row.predicates_per_pair:.1f} predicates "
            f"per pair, {row.saved_vs_every_program:.0%} saved"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
