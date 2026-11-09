"""The power analysis behind `tool-precondition.md` §8 (study 6).

It simulates the registered analysis by resampling the 45 repository units of the exploratory
data. A unit is a repository within a study, and the data are in
`results/lock-tool-check-2026-11-08/` and the gate records it reads.

    PYTHONPATH=src python -I docs/preregistration/tool-precondition-power.py \\
        > docs/preregistration/tool-precondition-power.json

For each simulated study, R units are drawn with replacement, and each hypothesis is decided as
§9 decides it:
- **H1:** per repository, the merged files' rejection rate minus the rejection rate of its
  ordinary commits' lock files in their own trees. The mean has a 95% t-interval, and the
  lower end must be above 0.
- **H2:** per repository, rule D's mismatch. The mean's lower end must be above 0.10.
- **H3:** pooled over the files where a package diverges and the tool accepts exactly one side
  (at least 20): the share where the first parent's file is the maintainer's set and the
  accepted side is not. Its Wilson upper bound must be below 0.10.

In the null worlds:
- **H1:** within each repository, the merged and ordinary checks are permuted together;
- **H2:** each of rule D's fires is wrong with probability exactly 0.10;
- **H3:** each tie-break file is a reverse with probability exactly 0.10.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from precondition_library.bench.lock_oracle import t_975

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "results" / "lock-tool-check-2026-11-08"
ANATOMY = ROOT / "results" / "lock-anatomy-2026-11-04"
GATES = ROOT / "results" / "divergence-gate-2026-11-08" / "gates.jsonl"
SIMULATIONS, SEED = 2000, 20261109
SIZES = (12, 15, 20, 25)


def kind(check: dict) -> str:
    v = check["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def gate_records() -> dict:
    found = {}
    for study in ("study-3", "study-4"):
        for line in (ANATOMY / f"{study}.jsonl").read_text("utf-8").splitlines():
            f = json.loads(line)
            found[(study, f["index"], f["path"])] = (
                f["kinds"].get("divergent", 0) > 0,
                f["predicted_reproduces"],
            )
    for line in GATES.read_text("utf-8").splitlines():
        case = json.loads(line)
        for f in case["files"]:
            found[("study-5", case["index"], f["path"])] = (
                f["divergent"] > 0,
                f["predicted_reproduces"],
            )
    return found


def units() -> list[dict]:
    """Per repository unit: its merged-file verdicts, its ordinary-commit verdicts, rule D's
    fires (wrong or not), and its tie-break files (tool's side right, first parent's right)."""
    gates = gate_records()
    found: dict = defaultdict(lambda: {"merged": [], "ordinary": [], "D": [], "tie": []})
    for study in ("study-3", "study-4", "study-5"):
        own = {}
        for line in (CHECK / f"{study}.own.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            own[(r["index"], r["path"])] = r["own_tree"]
        for line in (CHECK / f"{study}.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            u = found[(study, r["repo"])]
            merged = kind(r["check"]["merge"])
            if merged != "error":
                u["merged"].append(merged == "inconsistent")
            for side in ("first", "second", "base"):
                v = kind(own[(r["index"], r["path"])][side])
                if v != "error":
                    u["ordinary"].append(v == "inconsistent")
            diverges, merge_right = gates[(study, r["index"], r["path"])]
            sides = {s: kind(r["check"][s]) for s in ("first", "second")}
            passes = [s for s, v in sides.items() if v == "consistent"]
            tool = passes[0] if len(passes) == 1 and "error" not in sides.values() else None
            if not diverges:
                u["D"].append(not merge_right)
            elif tool:
                u["D"].append(not r["maintainer_set"][tool])
                u["tie"].append((r["maintainer_set"][tool], r["maintainer_set"]["first"]))
    return list(found.values())


def lower(values: list[float]) -> float:
    if len(values) < 2:
        return -math.inf
    centre = statistics.fmean(values)
    return centre - t_975(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))


def h1(sample: list[dict], rng: random.Random, null: bool) -> bool:
    diffs = []
    for u in sample:
        merged, ordinary = u["merged"], u["ordinary"]
        if not merged or not ordinary:
            continue
        if null:
            pooled = merged + ordinary
            rng.shuffle(pooled)
            merged, ordinary = pooled[: len(merged)], pooled[len(merged) :]
        diffs.append(sum(merged) / len(merged) - sum(ordinary) / len(ordinary))
    return lower(diffs) > 0


def h2(sample: list[dict], rng: random.Random, null: bool) -> bool:
    shares = []
    for u in sample:
        if u["D"]:
            wrong = [rng.random() < 0.10 for _ in u["D"]] if null else u["D"]
            shares.append(sum(wrong) / len(wrong))
    return lower(shares) > 0.10


def wilson_high(k: int, n: int) -> float:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    return centre + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)


def h3(sample: list[dict], rng: random.Random, null: bool) -> bool:
    ties = [pair for u in sample for pair in u["tie"]]
    if len(ties) < 20:
        return False
    if null:
        reverses = sum(rng.random() < 0.10 for _ in ties)
    else:
        reverses = sum(first and not tool for tool, first in ties)
    return wilson_high(reverses, len(ties)) < 0.10


def main() -> None:
    pool = units()
    rng = random.Random(SEED)
    rows = []
    for size in SIZES:
        tally = {f"{h}_{w}": 0 for h in ("h1", "h2", "h3") for w in ("power", "null")}
        for _ in range(SIMULATIONS):
            sample = [rng.choice(pool) for _ in range(size)]
            for name, test in (("h1", h1), ("h2", h2), ("h3", h3)):
                tally[f"{name}_power"] += test(sample, rng, null=False)
                tally[f"{name}_null"] += test(sample, rng, null=True)
        rows.append(
            {"repositories": size, **{k: round(v / SIMULATIONS, 3) for k, v in tally.items()}}
        )
    print(json.dumps({"units": len(pool), "simulations": SIMULATIONS, "seed": SEED, "rows": rows},
                     indent=2))  # fmt: skip


if __name__ == "__main__":
    main()
