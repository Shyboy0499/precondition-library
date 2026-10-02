"""One command for a live run: build, tune, frozen benchmark, Figure 1, and arm 1b.

The first live run (#163) went through a driver outside the repository, so the run that
found #157-#162 cannot be repeated from what is committed. This module is that driver,
committed: the stages are the repository's own functions, called in the order the spec
gives them, and every artifact lands under one output directory.

**Stages**, each writing under `out`:

1. **Build** (`bench.build_library`, ADR-0009/0010): compile once on the build seeds and
   gate twice, into `library-two-sided/` and `library-positive-only/`. Rows go to
   `build.jsonl`.
2. **Tune 2b** (`bench.soft_vote`, ADR-0016): learn the soft-vote threshold on the tune
   seeds against the two-sided library. No model call.
3. **Frozen benchmark** (ADR-0009): every arm against the two-sided library into
   `frozen.jsonl`, which `bench.report.write_report` turns into `report/`; arms 2 and 3
   against the positive-only library into `positive-only.jsonl`. The two are concatenated
   into `factorial.jsonl` for the admission factorial (ADR-0010) and nothing else, so the
   main report never mixes two libraries' rows for one arm.
4. **Figure 1** (`bench.library_pairs`, ADR-0022): the two-sided library's own matchers on
   the pair seeds' real sandboxes, into `primary/`, with 2b's Claim-2 verdict. No model
   call.
5. **Online arms 1 and 1b** (ADR-0017), optional: ReAct with and without its memory,
   each growing its own library, into `online/online.jsonl`.

`summary.json` and `summary.txt` record what ran and where each artifact is.

**The key.** Nothing in the package finds a key on its own (`provider.DeepSeekProvider`
takes it at construction). The caller names where it is, with exactly one of
`--api-key-env NAME` (the spec's §7 example, `DEEPSEEK_API_KEY`) or `--api-key-file PATH`.
The key itself is never an argument, where it would sit in shell history and the process
list, and nothing here prints or writes it.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from ..library import Library
from ..provider import DEFAULT_MODEL, DeepSeekProvider, Provider
from ..runtime.probes import evaluate_preconditions
from .build_library import build_library
from .coverage import operating_point, sweep
from .ledger import Arm
from .library_pairs import library_pair_outcomes
from .primary import primary_report, summary, write_primary_report
from .report import admission_factorial, write_report
from .run import run_benchmark
from .soft_vote import claim2_verdict, learn_soft_threshold, soft_vote_outcomes
from .splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS

MEASURED_FAULTS: tuple[str, ...] = ("diverged", "submodule_moved")
FROZEN_ARMS: tuple[Arm, ...] = (
    Arm.REACT,
    Arm.SEMANTIC,
    Arm.PRECONDITION,
    Arm.SOFT_VOTE,
    Arm.INTENT_KEY,
    Arm.GOLD,
)
"""Every arm a frozen run supports; arm 1b learns, so it is online only (ADR-0017)."""
FACTORIAL_ARMS: tuple[Arm, ...] = (Arm.SEMANTIC, Arm.PRECONDITION)
ONLINE_ARMS: tuple[Arm, ...] = (Arm.REACT, Arm.REACT_MEMORY)
SMOKE_EPISODE_SEEDS: tuple[int, ...] = EVAL_SEEDS[:4]
"""The default episode seeds: the first live run's four, so a re-run is comparable to it.
The full plan is all of `EVAL_SEEDS`, which `--episode-seeds 40` asks for."""


class LivePlan(BaseModel):
    """What a live run covers. The defaults are the first live run's (#163)."""

    faults: tuple[str, ...] = MEASURED_FAULTS
    build_seeds: tuple[int, ...] = SMOKE_SEEDS
    tune_seeds: tuple[int, ...] = TUNE_SEEDS
    pair_seeds: tuple[int, ...] = EVAL_SEEDS
    episode_seeds: tuple[int, ...] = SMOKE_EPISODE_SEEDS
    online: bool = True


class LiveSummary(BaseModel):
    """What ran and where it went; written to `summary.json`."""

    model: str
    plan: LivePlan
    admitted_two_sided: int
    admitted_positive_only: int
    compiled: int
    library_hash: str
    soft_threshold: float
    claim2: str
    claim2_reason: str
    figure1: str
    """`bench.primary.summary` of Figure 1: the comparison, or why it is vacuous."""
    factorial: list[dict]
    artifacts: dict[str, str]


def run_live(plan: LivePlan, *, provider: Provider, model: str, out: Path) -> LiveSummary:
    """Run every stage in order; `out` must not exist yet, so nothing is mixed in."""
    if out.exists():
        raise ValueError(f"{out} already exists; a live run writes into a fresh directory")
    out.mkdir(parents=True)
    faults = list(plan.faults)
    two_sided, positive_only = out / "library-two-sided", out / "library-positive-only"

    build = build_library(
        faults=faults,
        root=two_sided,
        ledger=out / "build.jsonl",
        provider=provider,
        model=model,
        seeds=plan.build_seeds,
        positive_only_root=positive_only,
    )
    if build.positive_only is None:
        raise RuntimeError("the build returned no positive-only library; the factorial needs it")

    library = Library(two_sided, evaluate_preconditions=evaluate_preconditions)
    soft_threshold = learn_soft_threshold(soft_vote_outcomes(library, faults, plan.tune_seeds))

    episode_seeds = list(plan.episode_seeds)
    frozen = run_benchmark(
        arms=list(FROZEN_ARMS),
        faults=faults,
        occurrences=len(episode_seeds),
        seeds=episode_seeds,
        out=out / "frozen.jsonl",
        model=model,
        provider=provider,
        frozen_library=two_sided,
        soft_threshold=soft_threshold,
    )
    ungated = run_benchmark(
        arms=list(FACTORIAL_ARMS),
        faults=faults,
        occurrences=len(episode_seeds),
        seeds=episode_seeds,
        out=out / "positive-only.jsonl",
        model=model,
        provider=provider,
        frozen_library=positive_only,
    )
    factorial_ledger = out / "factorial.jsonl"
    with factorial_ledger.open("wb") as handle:
        for ledger in (frozen, ungated):
            handle.write(ledger.read_bytes())
    write_report(frozen, out / "report")

    outcomes = library_pair_outcomes(library, faults, plan.pair_seeds)
    figure = primary_report(outcomes.arm2, outcomes.arm3, baselines=outcomes.baselines())
    write_primary_report(figure, out / "primary")
    verdict = claim2_verdict(sweep(outcomes.soft_vote), operating_point(outcomes.arm3))

    artifacts = {
        "build_ledger": "build.jsonl",
        "library_two_sided": two_sided.name,
        "library_positive_only": positive_only.name,
        "frozen_ledger": frozen.name,
        "positive_only_ledger": ungated.name,
        "factorial_ledger": factorial_ledger.name,
        "report": "report",
        "primary": "primary",
    }
    if plan.online:
        online = run_benchmark(
            arms=list(ONLINE_ARMS),
            faults=faults,
            occurrences=len(episode_seeds),
            seeds=episode_seeds,
            out=out / "online" / "online.jsonl",
            model=model,
            provider=provider,
        )
        artifacts["online_ledger"] = str(online.relative_to(out))

    result = LiveSummary(
        model=model,
        plan=plan,
        admitted_two_sided=build.admitted,
        admitted_positive_only=build.positive_only.admitted,
        compiled=len(build.programs),
        library_hash=build.library_hash,
        soft_threshold=soft_threshold,
        claim2=verdict.claim,
        claim2_reason=verdict.reason,
        figure1=summary(figure),
        factorial=[cell.model_dump(mode="json") for cell in admission_factorial(factorial_ledger)],
        artifacts=artifacts,
    )
    (out / "summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(_text(result), encoding="utf-8")
    return result


def _text(result: LiveSummary) -> str:
    lines = [
        f"model: {result.model}",
        f"compiled {result.compiled}; admitted two-sided {result.admitted_two_sided}, "
        f"positive-only {result.admitted_positive_only}",
        f"library hash: {result.library_hash}",
        f"2b threshold (tune seeds): {result.soft_threshold}",
        f"claim 2: {result.claim2} ({result.claim2_reason})",
        "",
        result.figure1,
        "",
        "admission factorial:",
        *(json.dumps(cell) for cell in result.factorial),
        "",
        "artifacts:",
        *(f"  {name}: {path}" for name, path in result.artifacts.items()),
    ]
    return "\n".join(lines) + "\n"


def read_api_key(path: Path) -> str:
    """The key from `path`, stripped; refuses a missing or empty file without echoing it."""
    if not path.is_file():
        raise SystemExit(f"no API key file at {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"the API key file at {path} is empty")
    return key


def read_api_key_env(name: str) -> str:
    """The key from the environment variable the caller named; refuses an unset or empty one."""
    key = os.environ.get(name, "").strip()
    if not key:
        raise SystemExit(f"the environment variable {name} holding the API key is unset or empty")
    return key


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.live",
        description="Build, tune, benchmark and report one live run into a fresh directory.",
    )
    key = parser.add_mutually_exclusive_group(required=True)
    key.add_argument("--api-key-env", metavar="NAME", help="environment variable holding the key")
    key.add_argument("--api-key-file", type=Path, metavar="PATH", help="file holding the key")
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--episode-seeds",
        type=int,
        default=len(SMOKE_EPISODE_SEEDS),
        help=f"how many of EVAL_SEEDS the episodes use (default {len(SMOKE_EPISODE_SEEDS)}; "
        f"the full plan is {len(EVAL_SEEDS)})",
    )
    parser.add_argument("--skip-online", action="store_true", help="skip arms 1 and 1b online")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.episode_seeds <= len(EVAL_SEEDS):
        raise SystemExit(f"--episode-seeds must be between 1 and {len(EVAL_SEEDS)}")
    plan = LivePlan(episode_seeds=EVAL_SEEDS[: args.episode_seeds], online=not args.skip_online)
    api_key = (
        read_api_key_env(args.api_key_env)
        if args.api_key_env is not None
        else read_api_key(args.api_key_file)
    )
    provider = DeepSeekProvider(api_key=api_key, model=args.model)
    try:
        result = run_live(plan, provider=provider, model=args.model, out=args.out)
    except BaseException:
        # A half-written run is not a run; keep it for debugging, but say so.
        if args.out.exists() and not (args.out / "summary.json").exists():
            print(f"incomplete run left in {args.out}")
        raise
    print(_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
