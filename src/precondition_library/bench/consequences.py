"""What a dispatch decision does to the repository when it is replayed (exploratory).

Figure 1 counts a mis-fire as a wrong *choice*: arm 2 picked a program the state does not
accept. It does not say what running that program would have done, which the README lists as
unmeasured ("mis-fires that end in a wrong repository"). Every piece needed is model-free --
the committed frozen library, the pair harness, the replay runtime and the episode loop's own
grader -- so this stage measures it without a provider.

For each eval pair the arms decide exactly as Figure 1 decided (`library_pair_outcomes`): arm 3
fires its first accepted program, and arm 2 fires its top-1 when its score reaches the
threshold at which the primary report matched it to arm 3's coverage. Each fired program is
then replayed on a fresh build of the pair's state and graded:

* on a fault's state, by `bench.run._grade`, the grader every episode uses: the fault's own
  checker, then `recorded_state_intact` over the fault's change surface;
* on a fault-free state, by whether anything changed at all: HEAD, the branch, every ref in
  both repositories and the working tree's status, before against after.

**This is not the pre-registered episode stage.** The frozen benchmark, the factorial and the
online arms need a model for the misses an arm hands to the agent. Nothing here solves a miss:
a pair no arm fires on is not replayed, so this measures fires only, and its rates are per fire.
The text is request-dependent and arm 3 is not, so arm 2 can fire different programs on the
pairs one environment holds; each (environment, program) is replayed once and every pair that
fired it shares the outcome.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..program import Program
from ..runtime.probes import evaluate_preconditions
from ..runtime.replay import replay
from ..sandbox import Sandbox, git_out, run_git
from ..tasks.faults import FAULTS, build_sandbox
from ..tasks.invariants import recorded_state_intact
from .coverage import _fires
from .heldout import HELD_OUT_FAULTS
from .library_pairs import FAULT_FREE, library_pair_outcomes
from .primary import primary_report
from .rescore import scorer
from .run import _grade
from .splits import EVAL_SEEDS

FIXED = "fixed"
"""A fault's state: the checker passed and the recorded state is intact."""
NOT_FIXED = "not fixed"
"""A fault's state: the checker refused it, and nothing recorded was lost."""
LOST = "lost recorded state"
"""A fault's state: the checker passed or not, but a recorded commit or upstream's history was
lost, or a commit landed outside the fault's change surface."""
NOTHING_RAN = "nothing ran"
"""The guard refused the body or it named a parameter the state cannot bind."""
UNCHANGED = "unchanged"
"""A fault-free state: nothing the snapshot reads moved."""
CHANGED = "changed"
"""A fault-free state: something moved, though nothing needed doing."""
UNGRADABLE = "ungradable"
"""The checker raised on the state the replay left."""


class Consequence(BaseModel):
    """One arm's fire on one pair, and what replaying it did."""

    arm: str
    seed: int
    environment: str
    program_id: str
    fired_variant: str | None
    correct: bool
    """Whether Figure 1 counted this fire as correct (the variant is acceptable here)."""
    outcome: str
    replay_ok: bool
    detail: str


class ConsequenceSummary(BaseModel):
    source: str
    library_hash: str
    scorer: dict[str, str]
    arm2_threshold: float | None
    pairs: int
    replays: int
    counts: dict[str, dict[str, int]]
    """Per `arm/correct` or `arm/wrong`, the number of fires with each outcome."""


def _snapshot(box: Sandbox) -> tuple[str, ...]:
    """Everything a no-op must leave alone: HEAD, branch, both repositories' refs, status."""
    return (
        git_out("rev-parse", "HEAD", cwd=box.work),
        run_git(("symbolic-ref", "-q", "HEAD"), cwd=box.work, check=False).stdout.strip(),
        git_out("for-each-ref", "--format=%(refname) %(objectname)", cwd=box.work),
        git_out("for-each-ref", "--format=%(refname) %(objectname)", cwd=box.upstream),
        run_git(("status", "--porcelain=v1", "-z", "--ignored"), cwd=box.work).stdout,
    )


def consequence_of(program: Program, seed: int, environment: str) -> tuple[str, bool, str]:
    """Replay `program` on a fresh build of `environment` at `seed`: (outcome, ok, detail)."""
    injected = [] if environment == FAULT_FREE else [environment]
    box = build_sandbox(seed, injected)
    try:
        before = _snapshot(box) if environment == FAULT_FREE else None
        result = replay(program, box)
        if result.refused or result.unbound_parameter:
            return NOTHING_RAN, result.ok, result.reason
        if before is not None:
            moved = _snapshot(box) != before
            return (CHANGED if moved else UNCHANGED), result.ok, result.reason
        fault = FAULTS[environment]
        try:
            fixed, _, _ = _grade(fault, box, seed)
            verdict = fault.check(box)
        except Exception as error:  # noqa: BLE001 - a checker that raises is the finding
            return UNGRADABLE, result.ok, f"{type(error).__name__}: {error}"
        if fixed:
            return FIXED, result.ok, verdict.detail
        intact = recorded_state_intact(box, surface=fault.change_surface_for_seed(seed))
        if not intact.ok:
            return LOST, result.ok, intact.detail
        return NOT_FIXED, result.ok, verdict.detail
    finally:
        box.destroy()


def run_consequences(
    run: Path,
    out: Path,
    *,
    scorer_name: str = "lexical",
    faults: Sequence[str] = HELD_OUT_FAULTS,
    seeds: Sequence[int] = EVAL_SEEDS,
) -> ConsequenceSummary:
    """Replay every fire of arms 3 and 2 on `run`'s frozen library and grade what it left."""
    if out.exists():
        raise ValueError(f"{out} already exists; the stage writes a fresh directory")
    similarity, identity = scorer(scorer_name)
    library = Library(
        run / "library-two-sided",
        similarity=similarity,
        evaluate_preconditions=evaluate_preconditions,
    )
    before = library.library_hash()
    by_id = {program.id: program for program in library.load_all()}
    outcomes = library_pair_outcomes(library, list(faults), list(seeds))
    report = primary_report(outcomes.arm2, outcomes.arm3, baselines=outcomes.baselines())
    threshold = report.matched.arm2.threshold if report.matched is not None else None

    fires: list[tuple[str, int, str, str, bool]] = []
    for pair, arm3, arm2 in zip(outcomes.pairs, outcomes.arm3, outcomes.arm2, strict=True):
        seed = pair.pair.seed
        if pair.accepted:
            fires.append(("arm3", seed, pair.environment, pair.accepted[0], arm3.decided_correctly))
        if report.matched is not None and pair.ranked and _fires(arm2, threshold):
            fires.append(
                ("arm2", seed, pair.environment, pair.ranked[0].id, arm2.decided_correctly)
            )

    replayed: dict[tuple[int, str, str], tuple[str, bool, str]] = {}
    rows: list[Consequence] = []
    for arm, seed, environment, program_id, correct in fires:
        key = (seed, environment, program_id)
        if key not in replayed:
            replayed[key] = consequence_of(by_id[program_id], seed, environment)
        outcome, ok, detail = replayed[key]
        rows.append(
            Consequence(
                arm=arm,
                seed=seed,
                environment=environment,
                program_id=program_id,
                fired_variant=by_id[program_id].variant,
                correct=correct,
                outcome=outcome,
                replay_ok=ok,
                detail=detail,
            )
        )

    after = library.library_hash()
    if before != after:
        raise RuntimeError(f"the stage changed the library it measured ({before} -> {after})")

    counts: dict[str, Counter[str]] = {}
    for row in rows:
        counts.setdefault(f"{row.arm}/{'correct' if row.correct else 'wrong'}", Counter())[
            row.outcome
        ] += 1
    summary = ConsequenceSummary(
        source=str(run),
        library_hash=before,
        scorer=identity,
        arm2_threshold=threshold,
        pairs=len(outcomes.pairs),
        replays=len(replayed),
        counts={key: dict(sorted(value.items())) for key, value in sorted(counts.items())},
    )
    out.mkdir(parents=True)
    with (out / "consequences.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")
    (out / "summary.json").write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (out / "summary.txt").write_text(text(summary), encoding="utf-8")
    return summary


def text(summary: ConsequenceSummary) -> str:
    lines = [
        f"Replayed fires (exploratory), {summary.source}: {summary.pairs} pairs, "
        f"{summary.replays} distinct replays, arm 2 at its matched threshold "
        f"{summary.arm2_threshold}",
    ]
    for key, outcomes in summary.counts.items():
        total = sum(outcomes.values())
        parts = ", ".join(f"{name} {count}" for name, count in outcomes.items())
        lines.append(f"  {key}: {total} fires -- {parts}")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.consequences",
        description="Replay each dispatch arm's fires and grade what they leave. No model call.",
    )
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--scorer", choices=("lexical", "embedding", "cross-encoder"), default="lexical"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    print(text(run_consequences(args.run, args.out, scorer_name=args.scorer)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
