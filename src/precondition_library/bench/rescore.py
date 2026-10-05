"""Re-measure a finished run's primary metric with another arm 2 scorer (#104).

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

Usage: `python -m precondition_library.bench.rescore --run RUN_DIR --scorer embedding --out DIR`.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ..library import Library
from ..program import ProgramStatus
from ..runtime.probes import evaluate_preconditions
from ..similarity import Similarity, lexical_similarity
from .live import LivePlan, LiveSummary, _build_episodes, _pair_level, _text

SCORERS = ("lexical", "embedding")


def scorer(name: str) -> tuple[Similarity, dict[str, str]]:
    """The named arm 2 scorer and what identifies it, for `rescore.json`."""
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
    raise ValueError(f"unknown scorer {name!r}; choose one of {', '.join(SCORERS)}")


def rescore(run: Path, out: Path, similarity: Similarity, identity: dict[str, str]) -> LiveSummary:
    """Recompute `run`'s pair-level stages into `out`, with arm 2 scored by `similarity`.

    `out` must not exist: like a live run, a rescore writes a fresh directory, so its figures
    cannot be mixed with another scorer's.
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
    _pair_level(result, plan, library, out)
    (out / "rescore.json").write_text(
        json.dumps({**identity, "run": str(run), "library_hash": result.library_hash}, indent=2)
        + "\n",
        encoding="utf-8",
    )
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    similarity, identity = scorer(args.scorer)
    result = rescore(args.run, args.out, similarity, identity)
    print(_text(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
