"""For the unreproduced files whose maintainer used only versions the sides had: how M differs
from the per-ecosystem three-way merge T (plain for npm's family, unified otherwise).

* `missing` = T − M, split by origin: a side's change (in L − B or U − B) the maintainer left
  out, or a pair both sides kept that the maintainer removed;
* `extra` = M − T, split by origin: a base pair the maintainer kept although a side changed it,
  or a side's pair the merge dropped (another side's removal).

    PYTHONPATH=src python recombine.py <study directory> <its .sandboxes/real-hosts>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

NPM = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
shape: Counter[str] = Counter()
sizes = []
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in row["files"]:
        if any(r["reproduces"] for r in f["results"]):
            continue
        s = {}
        for side in ("base", "first", "second", "merge"):
            text = la._show(repo, c[side], f["path"])
            s[side] = (la.packages(f["path"], text) if text is not None else None) or set()
        b, lo, up, mm = s["base"], s["first"], s["second"], s["merge"]
        if mm - (b | lo | up):
            continue  # a new resolution, counted elsewhere
        t = la.three_way(b, lo, up)
        if f["path"].rsplit("/", 1)[-1] not in NPM:
            t = la.unify(f["path"], t)
        missing, extra = t - mm, mm - t
        parts = []
        if missing & ((lo - b) | (up - b)):
            parts.append("left out a side's change")
        if missing & (b & lo & up):
            parts.append("removed what both kept")
        if extra & b:
            parts.append("kept a base version a side changed")
        if extra - b:
            parts.append("kept a pair the other side removed")
        # No difference: the merge equals M under `unify`'s deterministic tie-break, though the
        # study recorded it unreproduced under the set-order tie-break it ran with.
        shape[" + ".join(parts) or "equals the merge once ties are broken deterministically"] += 1
        sizes.append(len(missing) + len(extra))
total = sum(shape.values())
print(f"{study.name}: {total} recombined files")
for k, v in shape.most_common():
    print(f"  {v:>3}  {k}")
sizes.sort()
print(f"  pairs differing from the merge: median {sizes[len(sizes) // 2]}, max {sizes[-1]}")
