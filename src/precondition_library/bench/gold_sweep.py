"""Do the graders accept what the hand-written gold programs do? (ADR-0045)

A grader that refuses a correct resolution makes every figure read from it wrong in the same
direction, and nothing downstream can tell. Replaying held-out and real-host fires found four
such graders (ADR-0045), and each was confirmed the same way: a program known to be right was
graded as failing. This stage makes that check standing.

For every state a seed block builds, and every gold program of the state's fault, the gold
program is used the way a dispatcher would use it:

* its preconditions are evaluated on the state. A gold program whose preconditions do not hold
  is **not applicable** -- the lock-file gold refuses a held-out path by design -- and is not
  replayed;
* where they hold but the state does not accept its resolution, that is a **gold mis-fire**, a
  defect in the gold program's preconditions;
* where they hold and the resolution is accepted, the body is replayed on the state and graded
  by the two clauses every episode is (`bench.run._grade`): the recorded state over the fault's
  change surface, then the fault's checker. A refusal is a **grader or gold defect** until
  shown otherwise.

A new state source -- a held-out axis, a host, a family -- is not trusted until this stage
reports no defect on it. No model call; the gold programs are read from `bench/gold/`.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Sequence
from contextlib import nullcontext

from pydantic import BaseModel

from ..runtime.probes import evaluate_preconditions
from ..runtime.replay import replay
from ..sandbox import real_host_bases
from ..signatures import StateFingerprint
from ..tasks.faults import FAULTS, build_sandbox
from ..tasks.invariants import recorded_state_intact
from ..tasks.registry import EXCLUDED_FROM_BENCHMARK, ambiguous_intents
from .gold import load_gold_programs
from .realhost import host_for_seed
from .splits import EVAL_SEEDS, HELD_OUT_SEEDS

GRADED_OK = "graded ok"
REFUSED = "refused"
NOT_APPLICABLE = "not applicable"
MISFIRE = "gold mis-fire"


class SweepRow(BaseModel):
    fault: str
    seed: int
    variant: str
    outcome: str
    detail: str = ""


def sweep_faults() -> tuple[str, ...]:
    """Every fault with a measured intent, the families the graders are read for."""
    return tuple(
        sorted(
            intent.fault
            for intent in ambiguous_intents()
            if intent.fault not in EXCLUDED_FROM_BENCHMARK
        )
    )


def sweep(
    faults: Iterable[str], seeds: Iterable[int], *, real_hosts: bool = False
) -> list[SweepRow]:
    """One row per (fault, seed, gold variant): graded, refused, not applicable or mis-fired."""
    gold = load_gold_programs()
    intent_of = {intent.fault: intent for intent in ambiguous_intents()}
    rows: list[SweepRow] = []
    with real_host_bases(host_for_seed) if real_hosts else nullcontext():
        for fault in faults:
            intent = intent_of[fault]
            for seed in seeds:
                for variant, program in sorted(gold[fault].items()):
                    box = build_sandbox(seed, [fault])
                    try:
                        if not evaluate_preconditions(program, box).ok:
                            rows.append(
                                SweepRow(
                                    fault=fault, seed=seed, variant=variant, outcome=NOT_APPLICABLE
                                )
                            )
                            continue
                        accepted = intent.acceptable_variants(StateFingerprint.observe(box))
                        if variant not in accepted:
                            rows.append(
                                SweepRow(
                                    fault=fault,
                                    seed=seed,
                                    variant=variant,
                                    outcome=MISFIRE,
                                    detail=f"the state accepts {sorted(accepted)}",
                                )
                            )
                            continue
                        result = replay(program, box)
                        surface = FAULTS[fault].change_surface_for_seed(seed)
                        intact = recorded_state_intact(box, surface=surface)
                        verdict = intact if not intact.ok else FAULTS[fault].check(box)
                        rows.append(
                            SweepRow(
                                fault=fault,
                                seed=seed,
                                variant=variant,
                                outcome=GRADED_OK if verdict.ok else REFUSED,
                                detail="" if verdict.ok else f"{verdict.detail} ({result.reason})",
                            )
                        )
                    finally:
                        box.destroy()
    return rows


def defects(rows: Sequence[SweepRow]) -> list[SweepRow]:
    """The rows that are a grader's or a gold program's defect until shown otherwise."""
    return [row for row in rows if row.outcome in (REFUSED, MISFIRE)]


def text(rows: Sequence[SweepRow]) -> str:
    counts = Counter((row.fault, row.outcome) for row in rows)
    lines = []
    for fault in sorted({row.fault for row in rows}):
        parts = ", ".join(
            f"{outcome} {counts[(fault, outcome)]}"
            for outcome in (GRADED_OK, REFUSED, MISFIRE, NOT_APPLICABLE)
            if counts[(fault, outcome)]
        )
        lines.append(f"  {fault}: {parts}")
    found = defects(rows)
    lines.append(f"  defects: {len(found)}")
    lines.extend(
        f"    {row.fault} seed {row.seed} {row.variant}: {row.outcome} -- {row.detail}"
        for row in found
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.gold_sweep",
        description="Replay every applicable gold program on a seed block and grade it (ADR-0045).",
    )
    parser.add_argument("--seeds", choices=("eval", "held-out"), default="held-out")
    parser.add_argument("--real-host", action="store_true", help="over the pinned real histories")
    parser.add_argument("--faults", nargs="+", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    seeds = EVAL_SEEDS if args.seeds == "eval" else HELD_OUT_SEEDS
    rows = sweep(args.faults or sweep_faults(), seeds, real_hosts=args.real_host)
    print(text(rows), end="")
    return 1 if defects(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
