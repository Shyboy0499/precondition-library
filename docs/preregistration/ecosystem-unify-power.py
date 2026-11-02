"""The power analysis behind `ecosystem-unify.md` §8, from study 3's labels (already seen).

Study 4 asks, within each family of lock files, which of study 3's two package-level merges
reproduces the maintainer where they disagree: the plain three-way merge, or the same unified.

* **H1 (primary), both families together:** the merge the ecosystem's resolver predicts wins --
  unified for the one-version family, plain for npm's.
* **H2, the one-version family** (composer, Gemfile, poetry, uv, Pipfile, Cargo): the unified
  merge wins.
* **H3, npm's family** (package-lock, npm-shrinkwrap, yarn, pnpm): the plain merge wins.

The unit is a conflicted lock file on which exactly one of the two merges reproduces the
maintainer's package set (a *discordant* file). Each repository with a discordant file votes for
the predicted merge if it wins more of the repository's discordant files than it loses, against it
if it loses more; a tie casts no vote. H1 counts every discordant file of the repository, H2 and
H3 only those of their family. A
hypothesis is supported when its merge wins more votes and the exact two-sided sign test over the
votes gives p < 0.05 (`supported`). It needs at least six votes to be able to succeed.

A study is simulated by drawing `repositories` repositories from study 3's 27 with replacement,
and from each up to 15 cases with replacement. The null world swaps each discordant file's
winner with probability one half.

    python -I docs/preregistration/ecosystem-unify-power.py [STUDIES]
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

STUDY_3 = Path(__file__).resolve().parents[2] / "results/lock-oracle-2026-11-02/labels.jsonl"
NPM_FAMILY = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
PER_REPOSITORY = 15
DESIGNS = (10, 12, 15, 18, 20)
SEED = 20261103

Case = list[tuple[str, int]]
"""A case's discordant files: (family, +1 if the family's predicted merge won, else −1)."""


def family(path: str) -> str:
    return "npm" if path.rsplit("/", 1)[-1] in NPM_FAMILY else "one-version"


def cases() -> dict[str, list[Case]]:
    found: dict[str, list[Case]] = {}
    for line in STUDY_3.read_text("utf-8").splitlines():
        row = json.loads(line)
        case: Case = []
        for f in row["files"]:
            done = {r["action"]: r["reproduces"] for r in f["results"]}
            plain, unified = done["three_way"], done["three_way_unified"]
            if plain != unified:
                predicted = plain if family(f["path"]) == "npm" else unified
                case.append((family(f["path"]), 1 if predicted else -1))
        found.setdefault(row["repo"], []).append(case)
    return found


def sign_p(up: int, down: int) -> float:
    n = up + down
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(up, down) + 1)) / 2**n
    return min(1.0, 2 * tail)


def supported(votes: list[int]) -> bool:
    up, down = votes.count(1), votes.count(-1)
    return up > down and sign_p(up, down) < 0.05


def study(
    pool: dict[str, list[Case]], repositories: int, rng: random.Random, null: bool
) -> dict[str, list[int]]:
    """Each hypothesis's votes, one per repository with a discordant file it counts."""
    votes: dict[str, list[int]] = {"both": [], "one-version": [], "npm": []}
    for name in rng.choices(sorted(pool), k=repositories):
        drawn = rng.choices(pool[name], k=min(PER_REPOSITORY, len(pool[name])))
        tally = {"one-version": 0, "npm": 0}
        for case in drawn:
            for fam, won in case:
                tally[fam] += -won if null and rng.random() < 0.5 else won
        tally["both"] = tally["one-version"] + tally["npm"]
        for name, total in tally.items():
            if total:
                votes[name].append(1 if total > 0 else -1)
    return votes


def main() -> int:
    studies = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    pool = cases()
    results = {}
    for repositories in DESIGNS:
        rng = random.Random(SEED)
        row: dict[str, float] = {}
        for world in ("power", "false"):
            counts = dict.fromkeys(("h1", "h2", "h3", "h1_votes", "h2_votes", "h3_votes"), 0)
            for _ in range(studies):
                votes = study(pool, repositories, rng, null=world == "false")
                for name, which in (("h1", "both"), ("h2", "one-version"), ("h3", "npm")):
                    counts[name] += supported(votes[which])
                    counts[f"{name}_votes"] += len(votes[which])
            for name, n in counts.items():
                row[f"{name}_{world}"] = round(n / studies, 4)
        results[f"{repositories} repositories"] = row
        print(f"{repositories} repositories: " + ", ".join(f"{k} {v}" for k, v in row.items()))
    out = Path(__file__).with_name("ecosystem-unify-power.json")
    out.write_text(json.dumps({"studies": studies, "results": results}, indent=2) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
