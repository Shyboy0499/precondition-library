"""Recompute every judge figure from its cache, with no key and no tokens (ADR-0034 decision 5).

    PYTHONPATH=src python results/judge-2026-11-15/verification/recompute.py <scratch>

For each library and run, it rescores the frozen library through `bench.rescore` with the
committed cache and a provider that fails if it is ever called, into `<scratch>`. Then it checks
that the rescore made no call and wrote the same `summary.txt` as the committed one, its
output paths and spend aside. It exits non-zero on any difference. This script uses the
project's own pair-level code, because a Figure 1 point is defined by it; the scores it reads
are only the cache's.
"""

import shutil
import sys
from pathlib import Path

from precondition_library.bench import rescore as rs
from precondition_library.bench.judge_similarity import JudgeSimilarity
from precondition_library.provider import ProviderAuthError

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


class NoCalls:
    def complete(self, *, system, messages, tools=None):
        raise ProviderAuthError("the recompute must not call the provider", status_code=0)


SKIP = ("rescored_from", "primary:", "usage:")
"""Lines that name where the output went or what the scorer spent, which a recompute from the
cache changes by design: it spends nothing."""


def comparable(text: str) -> list[str]:
    return [line for line in text.splitlines() if not any(k in line for k in SKIP)]


def main() -> int:
    scratch = Path(sys.argv[1])
    problems = []
    for run in sorted(HERE.glob("run-*")):
        for rep in ("A", "B"):
            committed = run / rep
            out = scratch / run.name / rep
            if out.exists():
                shutil.rmtree(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            copy = out.parent / f"{rep}-cache.jsonl"
            shutil.copyfile(committed / "cache.jsonl", copy)
            judge = JudgeSimilarity(NoCalls(), cache_path=copy)
            rs.rescore(
                ROOT / "results" / "replicates-2026-10-05" / run.name,
                out,
                judge,
                {"scorer": "judge"},
            )
            same = comparable((out / "summary.txt").read_text("utf-8")) == comparable(
                (committed / "rescore" / "summary.txt").read_text("utf-8")
            )
            calls = judge.usage().calls
            print(f"{run.name} {rep}: provider calls {calls}; summary identical {same}")
            if calls or not same:
                problems.append(f"{run.name} {rep}")
    print("all recomputed from the caches" if not problems else f"differ: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
