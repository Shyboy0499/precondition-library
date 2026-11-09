"""The tool's check as a precondition: rules that fire a resolution only when an executed check
allows it, scored against the maintainer (#297, exploratory).

    python -I results/lock-tool-check-2026-11-08/dispatch.py results/lock-tool-check-2026-11-08

The unit is a conflicted `package-lock.json`, `pnpm-lock.yaml` or `composer.lock` of studies 3-5.
Two executable checks are available for each:

- **the divergence gate** (study 5): no package was changed by both sides to different versions.
  It licenses the per-ecosystem merge predicted by study 4. Read from
  `results/lock-anatomy-2026-11-04/` (studies 3 and 4) and study 5's `gates.jsonl`;
- **the tool's check** (`check.py`): exactly one side's lock file passes the ecosystem's own
  consistency check in the merge's tree. It licenses taking that side.

Each rule fires a resolution or refuses. A fire is right when its resolution is the maintainer's
package set. Mismatch is wrong fires over fires, with a Wilson interval. Files are pooled, so
the intervals ignore that files cluster in repositories, and a repository count is given beside
each figure.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANATOMY = ROOT / "results" / "lock-anatomy-2026-11-04"
GATES = ROOT / "results" / "divergence-gate-2026-11-08" / "gates.jsonl"
STUDIES = ("study-3", "study-4", "study-5")

RULES = (
    ("A", "the merge, always"),
    ("B", "the merge if no package diverges (the gate), else refuse"),
    ("C", "the one side the tool accepts, else refuse"),
    ("D", "the gate's merge; else the one side the tool accepts; else refuse"),
    ("E", "the one side the tool accepts; else the gate's merge; else refuse"),
    ("F", "control, no tool: the gate's merge; else the first parent's file"),
)


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    z = 1.959963984540054
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def mcnemar(b: int, c: int) -> float:
    """The exact two-sided McNemar test: a binomial test of b against b + c at one half."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def verdict(check: dict) -> str:
    v = check["verdict"]
    if v == "consistent":
        return "consistent"
    return "inconsistent" if v.startswith("inconsistent") else "error"


def gate_records() -> dict[tuple[str, int, str], tuple[bool, bool]]:
    """(study, case, path) -> (some package diverges, the predicted merge reproduces)."""
    found = {}
    for study in ("study-3", "study-4"):
        for line in (ANATOMY / f"{study}.jsonl").read_text("utf-8").splitlines():
            f = json.loads(line)
            diverges = f["kinds"].get("divergent", 0) > 0
            found[(study, f["index"], f["path"])] = (diverges, f["predicted_reproduces"])
    for line in GATES.read_text("utf-8").splitlines():
        case = json.loads(line)
        for f in case["files"]:
            found[("study-5", case["index"], f["path"])] = (
                f["divergent"] > 0,
                f["predicted_reproduces"],
            )
    return found


def decide(f: dict, rule: str) -> tuple[bool, bool]:
    """(fires, right) for one file. `picked` is the side the tool alone accepts, or None."""
    diverges, merge_right = f["diverges"], f["merge_right"]
    tool, tool_right = f["picked"], f["picked_right"]
    gate = not diverges
    if rule == "A":
        return True, merge_right
    if rule == "B":
        return gate, merge_right
    if rule == "C":
        return tool is not None, tool_right
    if rule == "D":
        if gate:
            return True, merge_right
        return tool is not None, tool_right
    if rule == "E":
        if tool is not None:
            return True, tool_right
        return gate, merge_right
    if rule == "F":
        return True, merge_right if gate else f["local_right"]
    raise ValueError(rule)


def main() -> None:
    folder = Path(sys.argv[1])
    gates = gate_records()
    files = []
    for study in STUDIES:
        for line in (folder / f"{study}.jsonl").read_text("utf-8").splitlines():
            r = json.loads(line)
            diverges, merge_right = gates[(study, r["index"], r["path"])]
            passes = [s for s in ("first", "second") if verdict(r["check"][s]) == "consistent"]
            judged = [s for s in ("first", "second") if verdict(r["check"][s]) != "error"]
            tool = passes[0] if len(passes) == 1 and len(judged) == 2 else None
            files.append(
                {
                    "study": study,
                    "repo": r["repo"],
                    "tool": r["tool"],
                    "diverges": diverges,
                    "merge_right": merge_right,
                    "picked": tool,
                    "picked_right": bool(tool) and r["maintainer_set"][tool],
                    "local_right": r["maintainer_set"]["first"],
                    "upstream_right": r["maintainer_set"]["second"],
                }
            )
    groups = [(s, [f for f in files if f["study"] == s]) for s in STUDIES]
    groups += [("all", files)]
    groups += [
        (f"all, {t}", [f for f in files if f["tool"] == t]) for t in ("npm", "pnpm", "composer")
    ]
    for name, mine in groups:
        repos = len({f["repo"] for f in mine})
        print(f"## {name}: {len(mine)} files, {repos} repositories")
        print("| rule | fires | coverage | wrong | mismatch [95% Wilson] |")
        print("| --- | ---: | ---: | ---: | --- |")
        for rule, label in RULES:
            tally: Counter = Counter()
            for f in mine:
                fires, right = decide(f, rule)
                tally["fires"] += fires
                tally["wrong"] += fires and not right
            low, high = wilson(tally["wrong"], tally["fires"])
            share = tally["wrong"] / tally["fires"] if tally["fires"] else math.nan
            print(
                f"| {rule}: {label} | {tally['fires']} | {tally['fires'] / len(mine):.2f} "
                f"| {tally['wrong']} | {share:.2f} [{low:.2f}, {high:.2f}] |"
            )
        picked = [f for f in mine if f["picked"]]
        if picked:
            first = sum(f["picked"] == "first" for f in picked)
            print(
                f"where the tool accepts one side ({len(picked)} files): it is the first parent's"
                f" in {first}; right: the tool's side {sum(f['picked_right'] for f in picked)},"
                f" the first parent's {sum(f['local_right'] for f in picked)},"
                f" the second parent's {sum(f['upstream_right'] for f in picked)}"
            )
            split = [f for f in picked if f["diverges"]]
            print(
                f"  of them, where a package diverges ({len(split)} files): right: the tool's side"
                f" {sum(f['picked_right'] for f in split)}, the first parent's"
                f" {sum(f['local_right'] for f in split)}"
            )
            better = sum(f["picked_right"] and not f["local_right"] for f in split)
            worse = sum(f["local_right"] and not f["picked_right"] for f in split)
            by_repo: Counter = Counter()
            for f in split:
                by_repo[f["repo"]] += int(f["picked_right"]) - int(f["local_right"])
            print(
                f"  paired: the tool's side right and the first parent's wrong {better},"
                f" the reverse {worse}; exact McNemar p = {mcnemar(better, worse):.3f};"
                f" repositories where the tool does better {sum(v > 0 for v in by_repo.values())},"
                f" worse {sum(v < 0 for v in by_repo.values())},"
                f" the same {sum(v == 0 for v in by_repo.values())}"
            )
        print()


if __name__ == "__main__":
    main()
