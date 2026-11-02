"""Which labelled files does unify's tie-break decide? For every file, every set of versions
sharing a key's highest release tuple is a tie; the verdict is checked under every choice.

    PYTHONPATH=src python results/ecosystem-unify-2026-11-02/verification/ties.py \\
        <study directory> <the run's .sandboxes/real-hosts>
"""

import itertools
import json
import sys
from pathlib import Path

from precondition_library.bench import lock_actions as la

study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
tied_files = decided = 0
for line in (study / "labels.jsonl").read_text().splitlines():
    r = json.loads(line)
    c = cases[r["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in r["files"]:
        sets = {
            k: la.packages(f["path"], t) if (t := la._show(repo, c[k], f["path"])) else None
            for k in ("base", "first", "second", "merge")
        }
        if sets["first"] is None or sets["second"] is None or sets["merge"] is None:
            continue
        tw = la.three_way(sets["base"] or set(), sets["first"], sets["second"])
        groups = {}
        for name, v in tw:
            groups.setdefault((name, la._compatible(f["path"], v)), []).append(v)
        ties = {}
        for key, vs in groups.items():
            top = max(la._release(v) for v in vs)
            best = [v for v in vs if la._release(v) == top]
            if len(best) > 1:
                ties[key] = best
        if not ties:
            continue
        tied_files += 1
        base = {(k[0], max(vs, key=la._release)) for k, vs in groups.items() if k not in ties}
        outcomes = set()
        for choice in itertools.product(*ties.values()):
            cand = base | {(k[0], v) for k, v in zip(ties, choice)}
            outcomes.add(cand == sets["merge"])
        recorded = next(x["reproduces"] for x in f["results"] if x["action"] == "three_way_unified")
        if len(outcomes) > 1:
            decided += 1
            print(
                "TIE DECIDES",
                r["index"],
                c["repo"],
                f["path"],
                {k[0]: v for k, v in ties.items()},
                "recorded",
                recorded,
            )
print(
    f"{study.name}: files with a tie {tied_files}; "
    f"files whose unified verdict the tie decides {decided}"
)
