"""The power analysis behind `lock-oracle.md` §8, from the exploratory pilot (#306).

It reads `results/lock-actions-2026-10-27/stage-A.jsonl`, the 30 stage-A conflicts already
measured package by package, and simulates the registered analysis: each figure is the mean of
the repositories' means, with a 95% t-interval over them.

* **H1 (coverage).** A repository's coverage is drawn from a beta distribution whose mean is the
  world's coverage and whose spread between repositories is the pilot's, estimated by the method
  of moments; its `PER_REPOSITORY` cases are then covered or not at that rate. Worlds: the
  pilot's pooled coverage (0.333), and coverage exactly at the bound (the null).
* **H2 (merge against each side).** The pilot's cases are resampled: repositories uniformly from
  the pilot's six, then each one's cases with replacement. Worlds: as piloted, and with both
  differences centred on zero over repositories (the null).
* **The percentile bootstrap over repositories** (study 1's interval) is run on H1's null too,
  for the comparison §8 reports, under the beta model and under a resampling model: the pilot's
  repositories and cases resampled as for H2, then each drawn covered case kept covered at the
  rate that puts the mean coverage over repositories exactly at the bound.

    python -I docs/preregistration/lock-oracle-power.py [STUDIES]
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

PILOT = Path(__file__).resolve().parents[2] / "results/lock-actions-2026-10-27/stage-A.jsonl"
COMPUTED = ("take_local", "take_upstream", "three_way", "three_way_unified")
BOUNDS = (0.10, 0.15)
PER_REPOSITORY = 15
DESIGNS = (10, 15, 20, 25)
SEED = 20261102
T_975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip


def cases() -> list[dict]:
    found = []
    for line in PILOT.read_text("utf-8").splitlines():
        case = json.loads(line)
        jaccard = {
            action: min(
                (r["jaccard"] or 0.0)
                for f in case["files"]
                for r in f["results"]
                if r["action"] == action
            )
            for action in COMPUTED
        }
        found.append(
            {
                "repo": case["repo"],
                "covered": float(any(case["reproduces"][a] for a in COMPUTED)),
                "local": jaccard["three_way_unified"] - jaccard["take_local"],
                "upstream": jaccard["three_way_unified"] - jaccard["take_upstream"],
            }
        )
    return found


def means(rows: list[dict], key: str) -> list[float]:
    repos = sorted({r["repo"] for r in rows})
    return [statistics.fmean(r[key] for r in rows if r["repo"] == g) for g in repos]


def t_low(values: list[float]) -> float:
    df = min(len(values) - 1, len(T_975))
    half = T_975[df - 1] * statistics.stdev(values) / math.sqrt(len(values))
    return statistics.fmean(values) - half


def bootstrap_low(values: list[float], rng: random.Random, resamples: int = 400) -> float:
    """Study 1's percentile interval over repositories, its lower end; equal-size repositories,
    so the mean of a resample's cases is the mean of its repositories' means."""
    drawn = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(resamples))
    return drawn[math.floor(0.025 * (resamples - 1))]


def between_repositories(pilot: list[dict]) -> float:
    """The spread of coverage between repositories beyond binomial noise (method of moments)."""
    repos = sorted({r["repo"] for r in pilot})
    rates = means(pilot, "covered")
    sizes = [sum(r["repo"] == g for r in pilot) for g in repos]
    pooled = statistics.fmean(r["covered"] for r in pilot)
    noise = statistics.fmean(pooled * (1 - pooled) / n for n in sizes)
    return math.sqrt(max(statistics.variance(rates) - noise, 0.0))


def beta(mean: float, sd: float, rng: random.Random) -> float:
    common = mean * (1 - mean) / sd**2 - 1
    return rng.betavariate(mean * common, (1 - mean) * common)


def coverage_study(mean: float, sd: float, repositories: int, rng: random.Random) -> list[float]:
    rates = [beta(mean, sd, rng) for _ in range(repositories)]
    return [sum(rng.random() < p for _ in range(PER_REPOSITORY)) / PER_REPOSITORY for p in rates]


def difference_study(pilot: list[dict], repositories: int, rng: random.Random) -> list[dict]:
    names = sorted({r["repo"] for r in pilot})
    rows = []
    for k, name in enumerate(rng.choices(names, k=repositories)):
        own = [r for r in pilot if r["repo"] == name]
        rows += [{**r, "repo": k} for r in rng.choices(own, k=PER_REPOSITORY)]
    return rows


def at_bound(pilot: list[dict], rows: list[dict], bound: float, rng: random.Random) -> list[dict]:
    """Each drawn case kept covered at the rate that makes the pilot's mean coverage over
    repositories `bound`: thinned case by case, so every study's truth is exactly the bound."""
    keep = bound / statistics.fmean(means(pilot, "covered"))
    return [{**r, "covered": float(r["covered"] and rng.random() < keep)} for r in rows]


def centred(pilot: list[dict]) -> list[dict]:
    local = statistics.fmean(means(pilot, "local"))
    upstream = statistics.fmean(means(pilot, "upstream"))
    return [{**r, "local": r["local"] - local, "upstream": r["upstream"] - upstream} for r in pilot]


def main() -> int:
    studies = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    pilot = cases()
    sd = between_repositories(pilot)
    pooled = statistics.fmean(r["covered"] for r in pilot)
    print(f"pilot: pooled coverage {pooled:.3f}, between-repository sd {sd:.3f}")
    results: dict[str, dict[str, float]] = {}
    for repositories in DESIGNS:
        rng = random.Random(SEED)
        row: dict[str, float] = {}
        for bound in BOUNDS:
            power = sum(
                t_low(coverage_study(pooled, sd, repositories, rng)) > bound for _ in range(studies)
            )
            wrong = wrong_bootstrap = 0
            for _ in range(studies):
                drawn = coverage_study(bound, sd, repositories, rng)
                wrong += t_low(drawn) > bound
                wrong_bootstrap += bootstrap_low(drawn, rng) > bound
            row[f"h1_power_bound_{bound}"] = power / studies
            row[f"h1_false_bound_{bound}"] = wrong / studies
            row[f"h1_false_bound_{bound}_bootstrap"] = wrong_bootstrap / studies
            wrong = wrong_bootstrap = 0
            for _ in range(studies // 4):
                drawn = means(
                    at_bound(pilot, difference_study(pilot, repositories, rng), bound, rng),
                    "covered",
                )
                wrong += t_low(drawn) > bound
                wrong_bootstrap += bootstrap_low(drawn, rng) > bound
            row[f"h1_false_bound_{bound}_resampled"] = wrong / (studies // 4)
            row[f"h1_false_bound_{bound}_resampled_bootstrap"] = wrong_bootstrap / (studies // 4)
        for world, base in (("power", pilot), ("false", centred(pilot))):
            hits = 0
            for _ in range(studies // 4):
                rows = difference_study(base, repositories, rng)
                hits += t_low(means(rows, "local")) > 0 and t_low(means(rows, "upstream")) > 0
            row[f"h2_{world}"] = hits / (studies // 4)
        results[f"{repositories} repositories"] = row
        print(f"{repositories} repositories: " + ", ".join(f"{k} {v:.3f}" for k, v in row.items()))
    out = Path(__file__).with_name("lock-oracle-power.json")
    summary = {
        "studies": studies,
        "pilot_pooled_coverage": round(pooled, 4),
        "between_repository_sd": round(sd, 4),
        "per_repository": PER_REPOSITORY,
        "results": results,
    }
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
