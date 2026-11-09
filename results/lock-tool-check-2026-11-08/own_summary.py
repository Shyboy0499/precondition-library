"""Inherited or made by the merge? `own_trees.py`'s verdicts, beside `check.py`'s (#297).

    python -I results/lock-tool-check-2026-11-08/own_summary.py results/lock-tool-check-2026-11-08

- **The base rate:** how often a lock file fails the check at an ordinary commit, in its own
  tree: the merge's two parents and their merge base.
- **The merges:** of the maintainers' merged files the check rejects, how many had both parents
  pass in their own trees (the merge made the inconsistency), and how many inherited it.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

STUDIES = ("study-3", "study-4", "study-5")


def kind(check: dict) -> str:
    v = check["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def wilson(k: int, n: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def share(k: int, n: int) -> str:
    if not n:
        return "-"
    low, high = wilson(k, n)
    return f"{k} of {n} ({k / n:.2f} [{low:.2f}, {high:.2f}])"


def main() -> None:
    folder = Path(sys.argv[1])
    merged, own = {}, {}
    for study in STUDIES:
        for line in (folder / f"{study}.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            merged[(study, r["index"], r["path"])] = r
        for line in (folder / f"{study}.own.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            own[(study, r["index"], r["path"])] = r
    assert set(merged) == set(own), "the two runs cover different files"
    print(
        "| tool | checks | the base rate: an ordinary commit's lock file rejected in its own tree"
        " | the merged file rejected | of those, both parents passed | of those, a parent failed |"
    )
    print("| --- | ---: | --- | --- | ---: | ---: |")  # fmt: skip
    totals: Counter = Counter()
    notes: list[str] = []
    for tool in ("npm", "pnpm", "composer", None):
        keys = [k for k in merged if tool is None or merged[k]["tool"] == tool]
        commits: Counter = Counter()
        for k in keys:
            for side in ("first", "second", "base"):
                commits[kind(own[k]["own_tree"][side])] += 1
        judged = commits["consistent"] + commits["inconsistent"]
        rejected = [k for k in keys if kind(merged[k]["check"]["merge"]) == "inconsistent"]
        made = inherited = 0
        for k in rejected:
            parents = [kind(own[k]["own_tree"][s]) for s in ("first", "second")]
            if parents == ["consistent", "consistent"]:
                made += 1
            elif "inconsistent" in parents:
                inherited += 1
        merges_judged = sum(kind(merged[k]["check"]["merge"]) != "error" for k in keys)
        parent_failed = [
            k
            for k in keys
            if "inconsistent" in [kind(own[k]["own_tree"][s]) for s in ("first", "second")]
            and kind(merged[k]["check"]["merge"]) != "error"
        ]
        repaired = sum(kind(merged[k]["check"]["merge"]) == "consistent" for k in parent_failed)
        notes.append(
            f"{tool or 'all'}: a parent's own lock file failed on {len(parent_failed)} files;"
            f" the merge passes on {repaired} of them"
        )
        print(
            f"| {tool or '**all**'} | {judged} | {share(commits['inconsistent'], judged)} "
            f"| {share(len(rejected), merges_judged)} | {made} | {inherited} |"
        )
        if tool is None:
            totals.update(commits)
    print()
    print("Checks count each commit once per file and case it serves, so a commit can recur.")
    for note in notes:
        print(note)
    # By repository: is the merged files' rejection rate above the repository's own base rate?
    rates: dict[str, list[int]] = {}
    for k, r in merged.items():
        cell = rates.setdefault(r["repo"], [0, 0, 0, 0])
        if kind(r["check"]["merge"]) != "error":
            cell[0] += kind(r["check"]["merge"]) == "inconsistent"
            cell[1] += 1
        for s in ("first", "second", "base"):
            if kind(own[k]["own_tree"][s]) != "error":
                cell[2] += kind(own[k]["own_tree"][s]) == "inconsistent"
                cell[3] += 1
    higher = lower = same = 0
    for bad, n, base_bad, base_n in rates.values():
        merged_rate = bad / n if n else 0.0
        base_rate = base_bad / base_n if base_n else 0.0
        higher += merged_rate > base_rate
        lower += merged_rate < base_rate
        same += merged_rate == base_rate
    n = higher + lower
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(higher, lower) + 1)) / 2**n)
    print(
        f"By repository: the merged files' rejection rate is above the base rate in {higher},"
        f" below it in {lower}, the same in {same}; two-sided sign test p = {p:.2g}"
    )
    # Composer's content-hash, the same way
    keys = [k for k in merged if merged[k]["tool"] == "composer"]
    stale_parents = sum(
        own[k]["own_tree"][s].get("hash") == "inconsistent"
        for k in keys
        for s in ("first", "second", "base")
    )
    hashed = sum(
        bool(own[k]["own_tree"][s].get("hash")) for k in keys for s in ("first", "second", "base")
    )
    stale_merges = sum(merged[k]["check"]["merge"].get("hash") == "inconsistent" for k in keys)
    print()
    print(
        f"Composer content-hash stale: ordinary commits {share(stale_parents, hashed)};"
        f" merged files {share(stale_merges, len(keys))}"
    )


if __name__ == "__main__":
    main()
