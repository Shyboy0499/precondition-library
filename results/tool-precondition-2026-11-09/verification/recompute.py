"""Recompute study 6's figures and decisions from its released files, importing nothing from the
project. Every value is compared with `report.json`; the script exits non-zero on a mismatch.

    python -I results/tool-precondition-<date>/verification/recompute.py

- **H1 and H2:** means over repositories, with a 95% t-interval (tool-precondition §6). t is
  computed here from the incomplete beta function, not taken from the project's table, so the
  interval's ends are compared to three decimals. (The table, `lock_oracle.T_975`, is exact to
  three decimals up to 30 degrees of freedom; the study has at most 25 repositories.)
- **H3:** the reverse share pooled over the tie-break files, with its Wilson interval.
- The descriptive figures of §7, and the decisions of §9.
"""

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BOUND, REVERSE_BOUND, MIN_REPOSITORIES, MIN_TIE_FILES = 0.10, 0.10, 15, 20
OWN = ("first", "second", "base")


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta I_x(a, b), by its continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1 - betainc(b, a, 1 - x)
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
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


def t_975(df: int) -> float:
    def cdf(t: float) -> float:
        return 1 - 0.5 * betainc(df / 2, 0.5, df / (df + t * t))

    low, high = 0.0, 50.0
    for _ in range(200):
        mid = (low + high) / 2
        low, high = (mid, high) if cdf(mid) < 0.975 else (low, mid)
    return (low + high) / 2


def mean_interval(values: list[float]) -> tuple[float, float, float] | None:
    if len(values) < 2:
        return None
    centre = statistics.fmean(values)
    half = t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return centre, centre - half, centre + half


def wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def kind(verdict: dict) -> str:
    v = verdict["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def accepted(row: dict) -> str | None:
    kinds = {s: kind(row["check"][s]) for s in ("first", "second")}
    passes = [s for s, k in kinds.items() if k == "consistent"]
    return passes[0] if len(passes) == 1 and "error" not in kinds.values() else None


def right(row: dict, side: str) -> bool:
    return row["local_reproduces"] if side == "first" else row["upstream_reproduces"]


def rule_d(row: dict) -> tuple[bool, bool]:
    if row["divergent"] == 0:
        return True, row["predicted_reproduces"]
    side = accepted(row)
    return side is not None, side is not None and right(row, side)


def main() -> int:
    report = json.loads((HERE / "report.json").read_text("utf-8"))
    rows = [json.loads(line) for line in (HERE / "files.jsonl").read_text("utf-8").splitlines()]
    problems: list[str] = []

    def check(name: str, mine: object, theirs: object) -> None:
        if isinstance(mine, float) and isinstance(theirs, float):
            same = abs(mine - theirs) <= 1e-9
        else:
            same = mine == theirs
        print(f"{'ok ' if same else 'BAD'} {name}: {mine} | {theirs}")
        if not same:
            problems.append(name)

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row)
    gaps, mismatch = [], []
    for files in by_repo.values():
        merged = [kind(r["check"]["merge"]) for r in files]
        merged = [k for k in merged if k != "error"]
        ordinary = [kind(r["own"][s]) for r in files for s in OWN]
        ordinary = [k for k in ordinary if k != "error"]
        if merged and ordinary:
            gaps.append(
                merged.count("inconsistent") / len(merged)
                - ordinary.count("inconsistent") / len(ordinary)
            )
        fires = [ok for fire, ok in map(rule_d, files) if fire]
        if fires:
            mismatch.append(sum(not ok for ok in fires) / len(fires))
    powered = min(len(gaps), len(mismatch)) >= MIN_REPOSITORIES
    check("files", len(rows), report["files"])
    check("repositories with a file", len(by_repo), report["repositories_with_a_file"])
    check("underpowered", not powered, report["underpowered"])

    def decide(found: tuple[float, float, float] | None, bound: float) -> str:
        if not powered:
            return "not decided"
        if found is None:
            return "not decided"
        return "supported" if found[1] > bound else "not supported"

    for name, values, bound in (("h1", gaps, 0.0), ("h2", mismatch, BOUND)):
        found = mean_interval(values)
        theirs = report[name]
        check(f"{name} repositories", len(values), theirs["repositories"])
        if found is not None:
            est = theirs["estimate"]
            check(f"{name} mean", found[0], est["statistic"])
            check(f"{name} low", round(found[1], 3), round(est["interval"]["low"], 3))
            check(f"{name} high", round(found[2], 3), round(est["interval"]["high"], 3))
        check(f"{name} decision", decide(found, bound), theirs["outcome"].split(":")[0])

    ties = [r for r in rows if r["divergent"] > 0 and accepted(r) is not None]
    reverses = sum(r["local_reproduces"] and not right(r, accepted(r) or "first") for r in ties)
    check("h3 tie files", len(ties), report["h3_tie_files"])
    check("h3 reverses", reverses, report["h3_reverse"])
    if ties:
        upper = wilson(reverses, len(ties))[1]
        check("h3 upper", round(upper, 9), round(report["h3_upper"], 9))
        if not powered:
            decision = "not decided"
        elif len(ties) < MIN_TIE_FILES:
            decision = "not decided"
        else:
            decision = "supported" if upper < REVERSE_BOUND else "not supported"
        check("h3 decision", decision, report["h3_outcome"].split(":")[0])
        print(
            f"    the 0.05 reading: Wilson upper {upper:.3f} {'<' if upper < 0.05 else '>='} 0.05"
        )

    fires = [rule_d(r) for r in rows]
    check(
        "rule D fires, wrong",
        (sum(f for f, _ in fires), sum(f and not ok for f, ok in fires)),
        (report["rules"]["D"]["fires"], report["rules"]["D"]["wrong"]),
    )
    gate = [(r["divergent"] == 0, r["predicted_reproduces"]) for r in rows]
    check(
        "rule B fires, wrong",
        (sum(f for f, _ in gate), sum(f and not ok for f, ok in gate)),
        (report["rules"]["B"]["fires"], report["rules"]["B"]["wrong"]),
    )
    better = sum(right(r, accepted(r) or "first") and not r["local_reproduces"] for r in ties)
    check("tie-break better", float(better), float(report["tie_gain"]["better"]))
    check("tie-break worse", float(reverses), float(report["tie_gain"]["worse"]))
    for tool in sorted({r["tool"] for r in rows}):
        files = [r for r in rows if r["tool"] == tool]
        merged = [kind(r["check"]["merge"]) for r in files]
        ordinary = [kind(r["own"][s]) for r in files for s in OWN]
        check(
            f"{tool} base rates",
            {
                "merged_rejected": merged.count("inconsistent"),
                "merged_judged": sum(k != "error" for k in merged),
                "ordinary_rejected": ordinary.count("inconsistent"),
                "ordinary_judged": sum(k != "error" for k in ordinary),
            },
            report["base_rates"][tool],
        )
    made: Counter = Counter()
    for r in rows:
        if kind(r["check"]["merge"]) != "inconsistent":
            continue
        parents = [kind(r["own"][s]) for s in ("first", "second")]
        if parents == ["consistent", "consistent"]:
            made["both parents passed"] += 1
        elif "inconsistent" in parents:
            made["a parent failed"] += 1
        else:
            made["a parent could not be judged"] += 1
    check("rejected merged files", dict(made), report["made_by_merge"])
    print("all figures agree" if not problems else f"{len(problems)} disagree: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
