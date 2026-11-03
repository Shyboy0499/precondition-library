"""Which kind of miss each dated npm run was on (exploratory): a *new resolution* (the
maintainer's set holds a version none of base, local or upstream had) or a *recombination*,
and whether npm reproduced it, came near, or failed from both sides.

    PYTHONPATH=src python results/lock-tool-dated-2026-11-03/kinds.py <study> <real-hosts> <log>
"""

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

study, hosts, log = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
count = Counter()
for line in log.read_text().splitlines():
    mm = re.match(r"^(\d+) (\S+) (\S+) \S+ (\{.*\})$", line)
    if not mm:
        continue
    idx, path, out = int(mm[1]), mm[3], ast.literal_eval(mm[4])
    c = cases[idx]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    s = {
        k: (la.packages(path, t) if (t := la._show(repo, c[k], path)) else None) or set()
        for k in ("base", "first", "second", "merge")
    }
    kind = (
        "new resolution" if s["merge"] - (s["base"] | s["first"] | s["second"]) else "recombination"
    )
    status = (
        "reproduced"
        if "reproduces" in out.values()
        else ("failed" if all(v == "failed" for v in out.values()) else "near")
    )
    count[(kind, status)] += 1
print(study.name, {f"{k} / {s}": v for (k, s), v in sorted(count.items())})
