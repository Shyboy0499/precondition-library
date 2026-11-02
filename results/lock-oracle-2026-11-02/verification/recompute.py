"""Recompute study 3's report from its files, importing nothing from the project.

Reads manifest.json, labels.jsonl and report.json; recomputes every figure of §6, §7 and §9
from the per-file, per-action results in labels.jsonl alone, re-deriving each case's
`reproduces`, `jaccard` and `covered` from its files rather than trusting them.

    python -I recompute.py <study directory>
"""

import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

COMPUTED = ("take_local", "take_upstream", "three_way", "three_way_unified")
T = (
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
)
study = Path(sys.argv[1])
report = json.loads((study / "report.json").read_text())
manifest = json.loads((study / "manifest.json").read_text())
rows = [
    json.loads(line) for line in (study / "labels.jsonl").read_text().splitlines() if line.strip()
]
bad = 0


def same(what, mine, theirs, tol=1e-9):
    global bad
    ok = (
        abs(mine - theirs) <= tol
        if isinstance(mine, float) and isinstance(theirs, float)
        else mine == theirs
    )
    bad += not ok
    print(("ok       " if ok else "MISMATCH ") + f"{what}: {mine!r} / {theirs!r}")


for r in rows:
    res = {a: [x for f in r["files"] for x in f["results"] if x["action"] == a] for a in COMPUTED}
    r["R"] = {a: all(x["reproduces"] for x in res[a]) for a in COMPUTED}
    r["J"] = {a: min((x["jaccard"] or 0.0) for x in res[a]) for a in COMPUTED}
    r["C"] = any(r["R"].values())
    if (
        r["R"] != r["reproduces"]
        or r["C"] != r["covered"]
        or any(abs(r["J"][a] - r["jaccard"][a]) > 1e-12 for a in COMPUTED)
    ):
        bad += 1
        print("MISMATCH case", r["index"])
print(f"checked {len(rows)} cases' own summaries")

cases = {c["index"]: c for c in manifest["cases"]}
same(
    "every label has its manifest case",
    all(r["index"] in cases and cases[r["index"]]["merge"] == r["merge"] for r in rows),
    True,
)
same("cases", len(rows), report["cases"])
repos = sorted({r["repo"] for r in rows})
same("repositories", len(repos), report["repositories_with_a_case"])
same("per repository", dict(Counter(r["repo"] for r in rows)), report["per_repository"])
same("exclusions", dict(Counter(e["reason"] for e in manifest["exclusions"])), report["exclusions"])
same("no repository above 15", max(Counter(r["repo"] for r in rows).values()) <= 15, True)


def est(value):
    m = [statistics.fmean(value(r) for r in rows if r["repo"] == g) for g in repos]
    c = statistics.fmean(m)
    h = T[min(len(m) - 1, 30) - 1] * statistics.stdev(m) / math.sqrt(len(m))
    return c, c - h, c + h


for name, value in (
    ("coverage", lambda r: float(r["C"])),
    ("merge_minus_local", lambda r: r["J"]["three_way_unified"] - r["J"]["take_local"]),
    ("merge_minus_upstream", lambda r: r["J"]["three_way_unified"] - r["J"]["take_upstream"]),
):
    c, lo, hi = est(value)
    same(f"{name} statistic", c, report[name]["statistic"])
    same(f"{name} low", lo, report[name]["interval"]["low"])
    same(f"{name} high", hi, report[name]["interval"]["high"])
same("pooled coverage", sum(r["C"] for r in rows) / len(rows), report["pooled_coverage"])
for a in COMPUTED:
    same(f"share {a}", sum(r["R"][a] for r in rows) / len(rows), report["action_share"][a])
    same(
        f"median Jaccard {a}",
        float(statistics.median(r["J"][a] for r in rows)),
        float(report["median_jaccard"][a]),
    )
same(
    "line-union share",
    sum(all(f["line_union"] for f in r["files"]) for r in rows) / len(rows),
    report["line_union_share"],
)
eco = {}
for r in rows:
    for f in r["files"]:
        e = eco.setdefault(f["path"].rsplit("/", 1)[-1], {"files": 0, "reproduced": 0})
        e["files"] += 1
        e["reproduced"] += any(x["reproduces"] for x in f["results"])
same("by ecosystem", eco, report["by_ecosystem"])

powered = len(rows) >= 150 and len(repos) >= 15
expected = ["1 power"]
if powered:
    cov = est(lambda r: float(r["C"]))
    local = est(lambda r: r["J"]["three_way_unified"] - r["J"]["take_local"])
    u = est(lambda r: r["J"]["three_way_unified"] - r["J"]["take_upstream"])
    expected += [
        f"2 H1:{'supported' if cov[1] > 0.10 else 'not supported'}",
        f"3 H2:{'supported' if local[1] > 0 and u[1] > 0 else 'not supported'}",
    ]
same("underpowered", not powered, report["underpowered"])
same(
    "decisions",
    expected,
    [
        d["rule"] if d["rule"] == "1 power" else d["rule"] + ":" + d["outcome"].split(":")[0]
        for d in report["decisions"]
    ],
)
print(f"{bad} mismatch(es)")
sys.exit(1 if bad else 0)
