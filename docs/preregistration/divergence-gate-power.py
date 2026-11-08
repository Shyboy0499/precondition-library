"""The power analysis behind `divergence-gate.md` §8, from studies 3 and 4 (already seen).

Study 5 tests a rule found after seeing studies 3 and 4 (`results/lock-anatomy-2026-11-04/`):
fire the predicted per-ecosystem merge on a conflict only when no package *diverges* (both sides
changed its versions, to different versions) in any of its conflicted lock files, and refuse
otherwise. Per repository, with the merge fired on every case (*always*) and only where nothing
diverges (*gate*):

* m_always = wrong / cases, and m_gate = wrong among the gate's fires / its fires.

Over repositories where the gate fires at least once:

* **H1 (primary):** mean(m_gate) > 0.10, by a 95% t-interval over repositories (study 3's
  analysis): the gate does not make the merge rarely wrong.
* **H2:** mean(m_always − m_gate) > 0, the same way: the gate lowers the merge's mismatch.
* **H3:** within repositories, on cases whose conflicted lock files are all in the one-version
  family, the merge reproduces the maintainer more often where nothing diverges than where
  something does. The statistic is the Mantel-Haenszel risk difference with repositories as
  strata, and its 95% interval is a percentile bootstrap over repositories.

A study is simulated by drawing `repositories` repositories with replacement from studies 3 and
4's 47, and from each up to 15 cases with replacement. Null worlds:

* H1: every one of the gate's fires is wrong with probability exactly 0.10.
* H2 and H3: divergence carries no information. Within each drawn repository, its cases'
  divergence flags are shuffled among its cases.

    python -I docs/preregistration/divergence-gate-power.py [STUDIES] [RESAMPLES]
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    (
        "results/lock-oracle-2026-11-02/labels.jsonl",
        "results/lock-anatomy-2026-11-04/study-3.jsonl",
    ),
    (
        "results/ecosystem-unify-2026-11-02/labels.jsonl",
        "results/lock-anatomy-2026-11-04/study-4.jsonl",
    ),
)
PER_REPOSITORY = 15
DESIGNS = (12, 15, 20, 25)
BOUND = 0.10
SEED = 20261108
T_975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
"""Study 3's table (`lock_oracle.T_975`)."""

Case = tuple[bool, bool, bool]
"""(a package diverges, the predicted merge reproduces every file, every file is one-version)."""


def cases() -> dict[str, list[Case]]:
    found: dict[str, list[Case]] = defaultdict(list)
    for labels, anatomy in SOURCES:
        files = {}
        for line in (ROOT / anatomy).read_text("utf-8").splitlines():
            f = json.loads(line)
            files[(f["index"], f["path"])] = f
        for line in (ROOT / labels).read_text("utf-8").splitlines():
            row = json.loads(line)
            mine = [files[(row["index"], f["path"])] for f in row["files"]]
            found[row["repo"]].append(
                (
                    any(f["kinds"].get("divergent", 0) for f in mine),
                    all(f["predicted_reproduces"] for f in mine),
                    all(f["family"] == "one-version" for f in mine),
                )
            )
    return dict(found)


def low_end(values: list[float]) -> float | None:
    """The lower end of the 95% t-interval of the mean."""
    if len(values) < 2:
        return None
    t = T_975[min(len(values) - 1, len(T_975)) - 1]
    return statistics.fmean(values) - t * statistics.stdev(values) / len(values) ** 0.5


def per_repository(drawn: list[list[Case]]) -> tuple[list[float], list[float]]:
    """Over repositories where the gate fires: m_gate, and m_always − m_gate."""
    gate, gains = [], []
    for repo in drawn:
        fires = [right for diverges, right, _ in repo if not diverges]
        if fires:
            m_gate = sum(not right for right in fires) / len(fires)
            gate.append(m_gate)
            gains.append(sum(not right for _, right, _ in repo) / len(repo) - m_gate)
    return gate, gains


def mantel_haenszel(drawn: list[list[Case]]) -> float | None:
    """The one-version risk difference, reproduced where nothing diverges minus where something
    does, over repositories that have one-version cases of both kinds."""
    num = den = 0.0
    for repo in drawn:
        calm = [right for diverges, right, one in repo if one and not diverges]
        split = [right for diverges, right, one in repo if one and diverges]
        if calm and split:
            weight = len(calm) * len(split) / (len(calm) + len(split))
            num += weight * (sum(calm) / len(calm) - sum(split) / len(split))
            den += weight
    return num / den if den else None


def bootstrap_low(drawn: list[list[Case]], resamples: int, rng: random.Random) -> float | None:
    """The 2.5th percentile of the Mantel-Haenszel difference over resampled repositories;
    None when fewer than 90% of the resamples define it."""
    values = []
    for _ in range(resamples):
        value = mantel_haenszel([rng.choice(drawn) for _ in drawn])
        if value is not None:
            values.append(value)
    if len(values) < 0.9 * resamples:
        return None
    values.sort()
    return values[int(0.025 * len(values))]


def draw(pool: dict[str, list[Case]], repositories: int, rng: random.Random) -> list[list[Case]]:
    names = sorted(pool)
    drawn = []
    for _ in range(repositories):
        own = pool[rng.choice(names)]
        drawn.append([rng.choice(own) for _ in range(min(PER_REPOSITORY, len(own)))])
    return drawn


def shuffled(drawn: list[list[Case]], rng: random.Random) -> list[list[Case]]:
    out = []
    for repo in drawn:
        flags = [c[0] for c in repo]
        rng.shuffle(flags)
        out.append([(f, c[1], c[2]) for f, c in zip(flags, repo, strict=True)])
    return out


def at_bound(drawn: list[list[Case]], rng: random.Random) -> list[list[Case]]:
    return [
        [(d, right if d else rng.random() >= BOUND, one) for d, right, one in repo]
        for repo in drawn
    ]


def above(value: float | None, bound: float) -> bool:
    return value is not None and value > bound


def main() -> None:
    studies = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    resamples = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    pool = cases()
    rng = random.Random(SEED)
    gate, gains = per_repository(list(pool.values()))
    observed = {
        "repositories": len(pool),
        "cases": sum(len(v) for v in pool.values()),
        "repositories_where_the_gate_fires": len(gate),
        "H1_mean_m_gate": statistics.fmean(gate),
        "H2_mean_gain": statistics.fmean(gains),
        "H3_mantel_haenszel": mantel_haenszel(list(pool.values())),
    }
    print(json.dumps(observed), flush=True)
    rows = []
    for n in DESIGNS:
        power: dict[str, int] = defaultdict(int)
        null: dict[str, int] = defaultdict(int)
        for _ in range(studies):
            drawn = draw(pool, n, rng)
            g, d = per_repository(drawn)
            power["H1"] += above(low_end(g), BOUND)
            power["H2"] += above(low_end(d), 0.0)
            power["H3"] += above(bootstrap_low(drawn, resamples, rng), 0.0)
            null["H1"] += above(low_end(per_repository(at_bound(drawn, rng))[0]), BOUND)
            flat = shuffled(drawn, rng)
            null["H2"] += above(low_end(per_repository(flat)[1]), 0.0)
            null["H3"] += above(bootstrap_low(flat, resamples, rng), 0.0)
        rows.append(
            {
                "repositories": n,
                "power": {h: power[h] / studies for h in ("H1", "H2", "H3")},
                "false_support": {h: null[h] / studies for h in ("H1", "H2", "H3")},
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    out = Path(__file__).with_suffix(".json")
    payload = {
        "seed": SEED,
        "studies": studies,
        "resamples": resamples,
        "observed": observed,
        "designs": rows,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
