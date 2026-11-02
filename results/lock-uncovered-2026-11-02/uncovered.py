"""What the maintainer did on the lock files no computed action reproduces (exploratory).

For every conflicted lock file of a study whose maintainer's package set none of the four
computed actions gives, it compares that set M with the base's, local side's and upstream's
(B, L, U) and asks:

* **new resolution:** does M hold a (package, version) pair none of B, L, U holds? Then the
  maintainer ran a resolver (regenerated, updated, or added a dependency in the merge);
  computed actions cannot produce a version nobody had. Split by whether the new pairs move
  packages the sides already had (`moved`) or add packages none had (`added`).
* **recombination:** M uses only pairs the sides had, but not the selection any action makes.
  Split by whether M drops packages every side kept (`dropped`).

    PYTHONPATH=src python uncovered.py <study directory> <its .sandboxes/real-hosts>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
kinds: Counter[str] = Counter()
by_eco: dict[str, Counter[str]] = {}
new_share = []
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in row["files"]:
        if any(r["reproduces"] for r in f["results"]):
            continue
        sets = {}
        for side in ("base", "first", "second", "merge"):
            text = la._show(repo, c[side], f["path"])
            sets[side] = (la.packages(f["path"], text) if text is not None else None) or set()
        b, lo, up, mm = sets["base"], sets["first"], sets["second"], sets["merge"]
        had = b | lo | up
        new = mm - had
        names_had = {n for n, _ in had}
        eco = f["path"].rsplit("/", 1)[-1]
        if new:
            moved = any(n in names_had for n, _ in new)
            added = any(n not in names_had for n, _ in new)
            kind = "new resolution: " + "+".join(
                k for k, v in (("moved", moved), ("added", added)) if v
            )
            new_share.append(len(new) / len(mm))
        else:
            kept_by_all = {n for n, _ in (b & lo & up)}
            dropped = any(n not in {x for x, _ in mm} for n in kept_by_all)
            kind = "recombination" + (": dropped" if dropped else "")
        kinds[kind] += 1
        by_eco.setdefault(eco, Counter())[kind.split(":")[0]] += 1
total = sum(kinds.values())
print(f"{study.name}: {total} unreproduced conflicted files")
for k, v in kinds.most_common():
    print(f"  {k:<40} {v:>4}  ({v / total:.0%})")
for eco, c in sorted(by_eco.items()):
    print(f"  {eco:<20} " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
if new_share:
    new_share.sort()
    median = new_share[len(new_share) // 2]
    print(f"  new pairs as a share of the maintainer's set: median {median:.3f}")
