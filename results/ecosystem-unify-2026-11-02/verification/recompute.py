"""Recompute study 4's report from its files, importing nothing from the project.

Reads manifest.json, labels.jsonl and report.json, and re-derives from the per-file, per-action
results every discordant file, each repository's vote, the three sign tests, H4's coverage and
interval, and the decisions, as `ecosystem-unify.md` §6-§9 state them.

    python -I recompute.py <study directory>
"""

import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

NPM = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
T = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179,
     2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
     2.060, 2.056, 2.052, 2.048, 2.045, 2.042)  # fmt: skip
study = Path(sys.argv[1])
report = json.loads((study / "report.json").read_text())
manifest = json.loads((study / "manifest.json").read_text())
rows = [json.loads(x) for x in (study / "labels.jsonl").read_text().splitlines() if x.strip()]
bad = 0


def same(what, mine, theirs, tol=1e-9):
    global bad
    if isinstance(mine, float) and isinstance(theirs, float):
        ok = abs(mine - theirs) <= tol
    else:
        ok = mine == theirs
    bad += not ok
    print(("ok       " if ok else "MISMATCH ") + f"{what}: {mine!r} / {theirs!r}")


def fam(path):
    return "npm" if path.rsplit("/", 1)[-1] in NPM else "one-version"


def done(f, action):
    return next(x["reproduces"] for x in f["results"] if x["action"] == action)


repos = sorted({r["repo"] for r in rows})
same("cases", len(rows), report["cases"])
same("repositories", len(repos), report["repositories_with_a_case"])
same("per repository", dict(Counter(r["repo"] for r in rows)), report["per_repository"])
same("at most 15 each", max(Counter(r["repo"] for r in rows).values()) <= 15, True)
same("exclusions", dict(Counter(e["reason"] for e in manifest["exclusions"])), report["exclusions"])
powered = len(repos) >= 12
same("underpowered", not powered, report["underpowered"])

for name, families in (("H1", {"one-version", "npm"}), ("H2", {"one-version"}), ("H3", {"npm"})):
    tally, seen, won, lost = Counter(), set(), 0, 0
    for r in rows:
        for f in r["files"]:
            plain, unified = done(f, "three_way"), done(f, "three_way_unified")
            if plain == unified or fam(f["path"]) not in families:
                continue
            hit = plain if fam(f["path"]) == "npm" else unified
            tally[r["repo"]] += 1 if hit else -1
            seen.add(r["repo"])
            won += hit
            lost += not hit
    up = sum(tally[x] > 0 for x in seen)
    down = sum(tally[x] < 0 for x in seen)
    n = up + down
    p = (
        1.0
        if n == 0
        else min(1.0, 2 * sum(math.comb(n, k) for k in range(min(up, down) + 1)) / 2**n)
    )
    t = report["tests"][name]
    same(f"{name} files won/lost", (won, lost), (t["files_won"], t["files_lost"]))
    same(
        f"{name} votes for/against/ties",
        (up, down, len(seen) - n),
        (t["votes_for"], t["votes_against"], t["ties"]),
    )
    same(f"{name} p", p, t["p"])
    if not powered:
        outcome = "not decided: the study is underpowered"
    elif n < 6:
        outcome = f"not decided: {n} votes, fewer than 6"
    elif up > down and p < 0.05:
        outcome = "supported"
    else:
        outcome = "not supported"
    same(f"{name} outcome", outcome, t["outcome"])

means = []
for g in repos:
    own = [r for r in rows if r["repo"] == g]
    means.append(statistics.fmean(float(any(r["reproduces"].values())) for r in own))
c = statistics.fmean(means)
h = T[min(len(means) - 1, 30) - 1] * statistics.stdev(means) / math.sqrt(len(means))
same("H4 coverage", c, report["coverage"]["statistic"])
same("H4 low", c - h, report["coverage"]["interval"]["low"])
same("H4 high", c + h, report["coverage"]["interval"]["high"])
h4 = (
    "not decided: the study is underpowered"
    if not powered
    else ("supported" if c - h > 0.10 else "not supported")
)
same("H4 outcome", h4, report["h4"])
eco = sum(
    all(
        done(f, "three_way" if fam(f["path"]) == "npm" else "three_way_unified") for f in r["files"]
    )
    for r in rows
)
same("predicted merge's share", eco / len(rows), report["ecosystem_share"])
for r in rows:
    for a in r["reproduces"]:
        if r["reproduces"][a] != all(done(f, a) for f in r["files"]):
            bad += 1
            print("MISMATCH case summary", r["index"], a)
print(f"{bad} mismatch(es)")
sys.exit(1 if bad else 0)
