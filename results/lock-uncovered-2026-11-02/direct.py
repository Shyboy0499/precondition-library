"""Of the side changes a maintainer left out (composer and npm-family lock files, recombinations
only): how many are direct dependencies named in the merged manifest (composer.json,
package.json) at the merge.

    PYTHONPATH=src python results/lock-uncovered-2026-11-02/direct.py <study> <its real-hosts cache>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

NPM = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json"}
MANIFEST = {
    "composer.lock": "composer.json",
    "package-lock.json": "package.json",
    "yarn.lock": "package.json",
    "pnpm-lock.yaml": "package.json",
}
SECTIONS = {
    "composer.json": ("require", "require-dev"),
    "package.json": ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"),
}
study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
count = Counter()
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in row["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if name not in MANIFEST or any(r["reproduces"] for r in f["results"]):
            continue
        s = {
            k: (la.packages(f["path"], t) if (t := la._show(repo, c[k], f["path"])) else None)
            or set()
            for k in ("base", "first", "second", "merge")
        }
        b, lo, up, mm = s["base"], s["first"], s["second"], s["merge"]
        if mm - (b | lo | up):
            continue
        t = la.three_way(b, lo, up)
        if name not in NPM:
            t = la.unify(f["path"], t)
        left_out = {n for n, _ in (t - mm) & ((lo - b) | (up - b))}
        if not left_out:
            continue
        mpath = f["path"][: -len(name)] + MANIFEST[name]
        text = la._show(repo, c["merge"], mpath)
        try:
            man = json.loads(text) if text else {}
        except json.JSONDecodeError:
            man = {}
        direct = (
            set().union(*[set((man.get(sec) or {}).keys()) for sec in SECTIONS[MANIFEST[name]]])
            if man
            else set()
        )
        count["files"] += 1
        count["left-out packages"] += len(left_out)
        count["of them direct"] += len(left_out & direct)
        count["files with a direct one"] += bool(left_out & direct)
print(study.name, dict(count))
