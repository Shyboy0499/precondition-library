"""Re-measure a finished run's primary metric with another arm 2 scorer (#104, #256, #264).

The primary metric is pair-level (ADR-0022): once a live run's build has frozen its library,
Figure 1, arm 2's baseline floor (spec §7 item 11) and Claim 2 are computed from that library's
own matchers on real sandboxes, with no model call. So the question a reviewer asks first of
the result -- *would a better text scorer close the gap?* -- needs no new build: the same
library, the same pairs and the same arm 3, with arm 2's `Similarity` seam filled by another
scorer.

This module does exactly that and nothing else. It reads a run directory (its `plan.json` and
`library-two-sided/`), opens the library with the chosen scorer behind `Library(similarity=...)`,
and runs `bench.live`'s own pair-level stage into a fresh output directory. Arm 3 does not read
the seam, so its operating point is unchanged by construction; arm 2's curve, its floor and the
matched comparison are what move. The build is never touched, and the scorer is recorded in
`rescore.json` beside the summary so a reader cannot mistake which arm 2 a figure measures.

Scorers:

* `lexical` -- the shipped seam (`similarity.lexical_similarity`); rescoring with it reproduces
  the run's own figures, which is the check that the rest is like for like.
* `embedding` -- `bench.embedding_similarity.EmbeddingSimilarity`, the pinned local
  sentence-transformer. It needs the `embedding` extra and the pinned revision downloadable
  or cached; it spends no provider tokens.
* `cross-encoder` -- `bench.cross_encoder_similarity.CrossEncoderSimilarity`, the pinned local
  reranker that reads the request and the program text together. Same extra, same zero tokens.
* `judge` -- `bench.judge_similarity.JudgeSimilarity`, a **model that reads the state** (issue
  #264, ADR-0034). The one scorer here that spends provider tokens, that needs a key, and that
  cannot be reproduced from the library alone: its per-pair scores are written to a
  `--judge-cache` file which is the evidence a figure is recomputed from, so the file is
  required rather than optional. Its spend is metered in the seam's own currency and recorded
  here, never folded into the LLM's tokens.

Usage: `python -m precondition_library.bench.rescore --run RUN_DIR --scorer embedding --out DIR`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ..library import Library
from ..program import ProgramStatus
from ..provider import (
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DeepSeekProvider,
    Provider,
)
from ..runtime.probes import evaluate_preconditions
from ..similarity import Similarity, lexical_similarity, similarity_usage
from .judge_similarity import PROMPT_VERSION, JudgeSimilarity
from .live import (
    LivePlan,
    LiveSummary,
    _build_episodes,
    _pair_level,
    _text,
    read_api_key,
    read_api_key_env,
)

SCORERS = ("lexical", "embedding", "cross-encoder", "judge")


def scorer(
    name: str,
    *,
    provider: Provider | None = None,
    judge_cache: Path | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> tuple[Similarity, dict[str, str]]:
    """The named arm 2 scorer and what identifies it, for `rescore.json`.

    `provider` and `judge_cache` are the judge's two requirements and nothing else's: the other
    three scorers are local and deterministic, and a caller that passes neither still gets them.
    """
    if name == "lexical":
        return lexical_similarity, {"scorer": "lexical"}
    if name == "embedding":
        from .embedding_similarity import EmbeddingSimilarity

        embedding = EmbeddingSimilarity()
        return embedding, {
            "scorer": "embedding",
            "model_id": embedding.model_id,
            "revision": embedding.revision,
        }
    if name == "cross-encoder":
        from .cross_encoder_similarity import CrossEncoderSimilarity

        reranker = CrossEncoderSimilarity()
        return reranker, {
            "scorer": "cross-encoder",
            "model_id": reranker.model_id,
            "revision": reranker.revision,
        }
    if name == "judge":
        if provider is None:
            raise ValueError(
                "scorer 'judge' needs a provider: pass --api-key-env NAME or --api-key-file PATH"
            )
        if judge_cache is None:
            raise ValueError(
                "scorer 'judge' needs --judge-cache PATH: the per-pair scores are the evidence, "
                "and a figure that cannot be recomputed from them is not a result (ADR-0034)"
            )
        return (
            JudgeSimilarity(provider, model=model, temperature=temperature, cache_path=judge_cache),
            {"scorer": "judge", "prompt_version": PROMPT_VERSION},
        )
    raise ValueError(f"unknown scorer {name!r}; choose one of {', '.join(SCORERS)}")


def rescore(run: Path, out: Path, similarity: Similarity, identity: dict[str, str]) -> LiveSummary:
    """Recompute `run`'s pair-level stages into `out`, with arm 2 scored by `similarity`.

    `out` must not exist: like a live run, a rescore writes a fresh directory, so its figures
    cannot be mixed with another scorer's.

    The seam's own spend is measured across the pair-level stage and written to `rescore.json`
    beside the scorer's identity. That is the one place a paid arm 2 can be accounted for here:
    the episode ledger's `embedding_tokens`/`embedding_calls` are written per episode by
    `bench.run`, and this stage writes no episode rows (issue #264).
    """
    if out.exists():
        raise ValueError(f"{out} already exists; a rescore writes into a fresh directory")
    recorded = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    plan = LivePlan.model_validate(recorded["plan"])
    root = run / "library-two-sided"
    library = Library(root, similarity=similarity, evaluate_preconditions=evaluate_preconditions)
    programs = library.load_all()
    if not programs:
        raise ValueError(f"{root} holds no program; there is nothing to rescore")
    out.mkdir(parents=True)
    result = LiveSummary(
        model=recorded["model"],
        plan=plan,
        admitted_two_sided=sum(p.status is ProgramStatus.ADMITTED for p in programs),
        admitted_positive_only=0,
        compiled=len(programs),
        library_hash=library.library_hash(),
        build=_build_episodes(run / "build.jsonl"),
        artifacts={"rescored_from": str(run)},
    )
    before = similarity_usage(similarity)
    _pair_level(result, plan, library, out)
    after = similarity_usage(similarity)
    usage = {
        "tokens": after.tokens - before.tokens,
        "calls": after.calls - before.calls,
    }
    result.artifacts["usage"] = (
        f"{usage['tokens']} seam token(s) in {usage['calls']} provider call(s)"
    )

    record: dict[str, object] = {
        **identity,
        "run": str(run),
        "library_hash": result.library_hash,
        "usage": usage,
    }
    reporter = getattr(similarity, "report", None)
    if reporter is not None:
        # The full configuration and the failure counters, which a terse identity tag cannot carry:
        # an unparseable reply is a fact about the figure, not a footnote (ADR-0034 decision 6).
        record["judge"] = {
            **reporter().model_dump(),
            "cache": str(getattr(similarity, "cache_path", "") or ""),
        }
    (out / "rescore.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(_text(result), encoding="utf-8")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m precondition_library.bench.rescore",
        description="Recompute a finished run's floor, Figure 1 and Claim 2 with another arm 2.",
    )
    parser.add_argument("--run", type=Path, required=True, help="a finished live run directory")
    parser.add_argument("--scorer", choices=SCORERS, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory")
    key = parser.add_mutually_exclusive_group()
    key.add_argument(
        "--api-key-env",
        metavar="NAME",
        help="environment variable holding the provider key (required by --scorer judge)",
    )
    key.add_argument(
        "--api-key-file",
        type=Path,
        metavar="PATH",
        help="file holding the provider key (required by --scorer judge)",
    )
    parser.add_argument(
        "--judge-cache",
        type=Path,
        help="where the judge writes its per-pair scores; required by --scorer judge",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="the judge's pinned model")
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="the judge's temperature; 0 by default, and not determinism on a hosted model",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider: Provider | None = None
    if args.scorer == "judge":
        if args.api_key_env is None and args.api_key_file is None:
            raise SystemExit(
                "scorer 'judge' needs a key: name where it is with --api-key-env NAME or "
                "--api-key-file PATH; the package reads neither on its own"
            )
        api_key = (
            read_api_key_env(args.api_key_env)
            if args.api_key_env is not None
            else read_api_key(args.api_key_file)
        )
        provider = DeepSeekProvider(api_key=api_key, model=args.model, temperature=args.temperature)
    similarity, identity = scorer(
        args.scorer,
        provider=provider,
        judge_cache=args.judge_cache,
        model=args.model,
        temperature=args.temperature,
    )
    result = rescore(args.run, args.out, similarity, identity)
    print(_text(result), end="")
    print(f"seam usage: {result.artifacts.get('usage', 'none')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
