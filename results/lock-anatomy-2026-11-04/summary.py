"""Summarise `anatomy.py`'s per-file output with the studies' registered labels (exploratory).

    python results/lock-anatomy-2026-11-04/summary.py \\
        <study-3 directory> <study-3 anatomy.jsonl> <study-4 directory> <study-4 anatomy.jsonl>

Prints, per study:

1. conflicted files by family and by how many packages diverge, with the share the predicted
   per-ecosystem merge reproduces;
2. for files with a divergent package, how far a tie-break on those packages could go;
3. what maintainers kept of divergent packages, file by file;
4. why the predicted merge misses files where nothing diverges;
5. dispatch rules that read only the three sides, scored case by case against the maintainer;
6. per repository, the share of cases with a divergent package against registered coverage.
"""

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    z, p = 1.959963984540054, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def bucket(n: int) -> str:
    return "0" if n == 0 else "1" if n == 1 else "2-4" if n < 5 else "5+"


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den


def report(study: Path, anatomy: Path) -> None:
    files = [json.loads(line) for line in anatomy.read_text().splitlines()]
    labels = [json.loads(line) for line in (study / "labels.jsonl").read_text().splitlines()]
    by_case: dict[int, dict[str, dict]] = defaultdict(dict)
    for f in files:
        by_case[f["index"]][f["path"]] = f
    print(f"== {study.name}: {len(labels)} cases, {len(files)} conflicted files")

    print("\n1. files by family and divergent packages: files, predicted merge reproduces")
    for family in ("npm", "one-version"):
        for b in ("0", "1", "2-4", "5+"):
            group = [
                f
                for f in files
                if f["family"] == family and bucket(f["kinds"].get("divergent", 0)) == b
            ]
            hit = sum(f["predicted_reproduces"] for f in group)
            print(f"   {family:11s} {b:>3s}  {len(group):4d}  {hit:4d}  {hit / len(group):.2f}")
    none = [f for f in files if f["kinds"].get("divergent", 0) == 0]
    print(f"   no divergent package: {len(none)} of {len(files)} ({len(none) / len(files):.2f})")
    kinds: Counter[str] = Counter()
    for f in files:
        kinds.update(f["kinds"])
    print(f"   package names by kind, all files: {dict(sorted(kinds.items()))}")

    print("\n2. files with a divergent package: predicted, right outside them, tie-breaks")
    for family in ("npm", "one-version"):
        d = [f for f in files if f["family"] == family and f["kinds"].get("divergent", 0)]
        ties = {k: sum(f["tie_breaks"][k] for f in d) for k in ("local", "upstream", "highest")}
        predicted = sum(f["predicted_reproduces"] for f in d)
        print(
            f"   {family:11s} files {len(d)}, predicted {predicted},"
            f" right outside divergent {sum(f['outside_divergent'] for f in d)},"
            f" tie-breaks {ties}, any {sum(any(f['tie_breaks'].values()) for f in d)}"
        )

    print("\n3. what the maintainer kept of divergent packages, per file")
    for family in ("npm", "one-version"):
        uniform: Counter[str] = Counter()
        for f in files:
            if f["family"] != family or not f["divergent"]:
                continue
            choices = {d["choice"] for d in f["divergent"]}
            uniform[
                "all local's"
                if choices == {"local's"}
                else "all upstream's"
                if choices == {"upstream's"}
                else "mixed or other"
            ] += 1
        print(f"   {family:11s} {dict(sorted(uniform.items()))}")

    print("\n4. predicted merge misses with nothing divergent: why (overlapping)")
    miss = [f for f in none if not f["predicted_reproduces"]]
    print(
        f"   {len(miss)} files: a version no side had {sum(f['new_versions'] > 0 for f in miss)},"
        " a one-sided change not taken"
        f" {sum(any(k != 'took the change' for k in f['one_sided']) for f in miss)},"
        " an untouched package changed"
        f" {sum(f['kinds'].get('untouched, changed in the merge', 0) > 0 for f in miss)}"
    )

    print("\n5. rules over the three sides, case by case")
    tally: dict[str, Counter] = defaultdict(Counter)
    per_repo: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    divergent_share: dict[str, list[bool]] = defaultdict(list)
    covered: dict[str, list[bool]] = defaultdict(list)
    for row in labels:
        info = by_case[row["index"]]
        f_rows = row["files"]

        def all_files(action: str, f_rows: list = f_rows) -> bool:
            return all({r["action"]: r["reproduces"] for r in f["results"]}[action] for f in f_rows)

        predicted = all(info[f["path"]]["predicted_reproduces"] for f in f_rows)
        diverges = any(info[f["path"]]["kinds"].get("divergent", 0) for f in f_rows)
        local_wins = all(info[f["path"]]["tie_breaks"]["local"] for f in f_rows)
        rules = {
            "merge, always": (True, predicted),
            "merge, local's version where a package diverges": (True, local_wins),
            "merge if nothing diverges, else take_local": (
                True,
                predicted if not diverges else all_files("take_local"),
            ),
            "merge if nothing diverges, else refuse": (not diverges, predicted),
            "take_local, always": (True, all_files("take_local")),
        }
        for name, (fire, right) in rules.items():
            for t in (tally[name], per_repo[name][row["repo"]]):
                t["cases"] += 1
                t["fires"] += fire
                t["right"] += fire and right
        divergent_share[row["repo"]].append(diverges)
        covered[row["repo"]].append(row["covered"])
    for name, t in tally.items():
        wrong = t["fires"] - t["right"]
        low, high = wilson(wrong, t["fires"])
        mean_right = statistics.mean(r["right"] / r["cases"] for r in per_repo[name].values())
        print(
            f"   {name:48s} fires {t['fires']:3d}/{t['cases']}, wrong {wrong:3d},"
            f" mismatch {wrong / t['fires']:.3f} [{low:.3f}, {high:.3f}],"
            f" right per case (repository mean) {mean_right:.3f}"
        )

    print("\n6. per repository: share of cases with a divergent package, registered coverage")
    repos = sorted(divergent_share)
    xs = [statistics.mean(divergent_share[r]) for r in repos]
    ys = [statistics.mean(covered[r]) for r in repos]
    print(f"   {len(repos)} repositories, Spearman rho {spearman(xs, ys):.3f}")
    for r, x, y in sorted(zip(repos, xs, ys, strict=True), key=lambda t: t[1]):
        print(f"   {r:40s} {x:.2f}  {y:.2f}")
    print()


report(Path(sys.argv[1]), Path(sys.argv[2]))
report(Path(sys.argv[3]), Path(sys.argv[4]))
