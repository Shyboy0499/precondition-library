"""Recompute study 5's figures and decisions from its released files, importing nothing from the
project. Every value is compared with `report.json`; the script exits non-zero on a mismatch.

    python -I results/divergence-gate-2026-11-08/verification/recompute.py

* H1 and H2: means over repositories where the gate fires, with a 95% t-interval
  (divergence-gate §6). t is computed here from the incomplete beta function, not taken from the
  project's table.
* H3: the Mantel-Haenszel risk difference on one-version cases, and its percentile bootstrap,
  2,000 resamples of the repositories, seed 20261108 (§6), redone step by step.
* The descriptive figures of §7, and the decisions of §9.
"""

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BOUND, MIN_REPOSITORIES, RESAMPLES, SEED = 0.10, 15, 2000, 20261108


def t_975(df: int) -> float:
    """Student's t quantile at 0.975, by bisection on the regularised incomplete beta."""

    def cdf(t: float) -> float:
        x = df / (df + t * t)
        return 1 - 0.5 * betainc(df / 2, 0.5, x)

    low, high = 0.0, 50.0
    for _ in range(200):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) < 0.975 else (low, mid)
    return (low + high) / 2


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta I_x(a, b), by its continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x > (a + 1) / (a + b + 2):
        return 1 - betainc(b, a, 1 - x)
    c, d, f = 1.0, 0.0, 1.0
    for i in range(400):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1 + num * d
        d = 1 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1 + num / (c if abs(c) > 1e-300 else 1e-300)
        f *= c * d
        if abs(1 - c * d) < 1e-15:
            break
    return front * (f - 1) / a


def mean_interval(values: list[float]) -> tuple[float, float, float]:
    centre = statistics.fmean(values)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return centre, centre - half, centre + half


def mh(groups: list[list[dict]]) -> float | None:
    num = den = 0.0
    for group in groups:
        calm = [c["predicted_reproduces"] for c in group if c["one_version"] and not c["diverges"]]
        split = [c["predicted_reproduces"] for c in group if c["one_version"] and c["diverges"]]
        if calm and split:
            w = len(calm) * len(split) / (len(calm) + len(split))
            num += w * (sum(calm) / len(calm) - sum(split) / len(split))
            den += w
    return num / den if den else None


def close(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance


def main() -> int:
    report = json.loads((HERE / "report.json").read_text("utf-8"))
    gates = [json.loads(line) for line in (HERE / "gates.jsonl").read_text("utf-8").splitlines()]
    labels = [json.loads(line) for line in (HERE / "labels.jsonl").read_text("utf-8").splitlines()]
    problems = []

    def check(name: str, mine: object, theirs: object) -> None:
        same = (
            close(mine, theirs)
            if isinstance(mine, float) and isinstance(theirs, float)
            else mine == theirs
        )
        print(f"{'ok ' if same else 'BAD'} {name}: {mine} | {theirs}")
        if not same:
            problems.append(name)

    for g in gates:  # each case's flags follow from its files
        assert g["diverges"] == any(f["divergent"] for f in g["files"])
        assert g["predicted_reproduces"] == all(f["predicted_reproduces"] for f in g["files"])
        assert g["one_version"] == all(f["family"] == "one-version" for f in g["files"])
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for g in gates:
        by_repo[g["repo"]].append(g)
    by_repo = dict(sorted(by_repo.items()))
    m_gate, gains = [], []
    for cases in by_repo.values():
        fires = [c for c in cases if not c["diverges"]]
        if fires:
            gate = sum(not c["predicted_reproduces"] for c in fires) / len(fires)
            always = sum(not c["predicted_reproduces"] for c in cases) / len(cases)
            m_gate.append(gate)
            gains.append(always - gate)
    check("cases", len(gates), report["cases"])
    check("repositories with a case", len(by_repo), report["repositories_with_a_case"])
    check(
        "repositories where the gate fires",
        len(m_gate),
        report["repositories_where_the_gate_fires"],
    )
    powered = len(m_gate) >= MIN_REPOSITORIES
    check("underpowered", not powered, report["underpowered"])

    def decide(centre_low_high: tuple[float, float, float] | None, bound: float) -> str:
        if not powered:
            return "not decided"
        if centre_low_high is None:
            return "not decided"
        _, low, high = centre_low_high
        return "supported" if low > bound else "not supported"

    for name, values, bound in (("h1", m_gate, BOUND), ("h2", gains, 0.0)):
        centre, low, high = mean_interval(values)
        est = report[name]["estimate"]
        check(f"{name} mean", centre, est["statistic"])
        check(f"{name} low", round(low, 3), round(est["interval"]["low"], 3))
        check(f"{name} high", round(high, 3), round(est["interval"]["high"], 3))
        check(f"{name} decision", decide((centre, low, high), bound),
              report[name]["outcome"].split(":")[0])  # fmt: skip

    groups = list(by_repo.values())
    centre = mh(groups)
    rng = random.Random(SEED)
    values = []
    for _ in range(RESAMPLES):
        value = mh([rng.choice(groups) for _ in groups])
        if value is not None:
            values.append(value)
    values.sort()
    low, high = (
        values[int(0.025 * len(values))],
        values[min(len(values) - 1, int(0.975 * len(values)))],
    )
    est = report["h3"]["estimate"]
    check("h3 statistic", centre, est["statistic"])
    check("h3 low", low, est["interval"]["low"])
    check("h3 high", high, est["interval"]["high"])
    check("h3 decision", decide((centre, low, high), 0.0), report["h3"]["outcome"].split(":")[0])

    for gate, key in ((False, "always"), (True, "gate")):
        fired = [g for g in gates if not (gate and g["diverges"])]
        wrong = sum(not g["predicted_reproduces"] for g in fired)
        check(
            f"{key} fires/wrong", (len(fired), wrong), (report[key]["fires"], report[key]["wrong"])
        )
    check(
        "gate fire share",
        sum(not g["diverges"] for g in gates) / len(gates),
        report["gate_fire_share"],
    )
    cells: dict = {
        f: {"none diverges": [0, 0], "some diverges": [0, 0]} for f in ("npm", "one-version")
    }
    for g in gates:
        for f in g["files"]:
            cell = cells[f["family"]]["some diverges" if f["divergent"] else "none diverges"]
            cell[0] += 1
            cell[1] += f["predicted_reproduces"]
    check("files by family", cells, report["files_by_family"])
    covered: dict[str, list[bool]] = defaultdict(list)
    for row in labels:
        covered[row["repo"]].append(row["covered"])
    centre, low, high = mean_interval([sum(v) / len(v) for v in covered.values()])
    check("coverage", round(centre, 9), round(report["coverage"]["statistic"], 9))
    check("coverage low", round(low, 3), round(report["coverage"]["interval"]["low"], 3))
    print("all figures agree" if not problems else f"{len(problems)} disagree: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
