"""The anatomy of a lock-file conflict (exploratory, seen data): what conflicts at the level of
packages when git reports a conflict at the level of lines, and what maintainers did with it.

Every conflicted lock file of a study is read, at base, local, upstream and merge, into a map
from package name to its set of versions. Each name is then one of:

* **untouched**: neither side changed its versions;
* **one-sided**: exactly one side changed them (added, removed, or moved the package);
* **convergent**: both sides changed them to the same versions;
* **divergent**: both sides changed them, to different versions. This is a conflict at the level
  of packages; every other kind has a single answer that a three-way merge computes.

For each divergent name the maintainer's versions are classed against the sides'. For each file
the registered labels say whether the predicted per-ecosystem merge reproduced it (unified for the
one-version family, plain for npm's, as study 4 registered).

Three tie-breaks are then tried on the divergent names alone, everything else being the predicted
merge recomputed here: local's versions, upstream's, or the single highest of either side's. And
`outside_divergent` records whether the maintainer's set equals the recomputed merge on every
other name, which bounds what any tie-break on divergent names could recover. One JSON line per
file is written to `<out>`.

    PYTHONPATH=src python results/lock-anatomy-2026-11-04/anatomy.py \\
        <study> <its real-hosts cache> <out.jsonl>
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from precondition_library.bench import ecosystem_unify as eu
from precondition_library.bench import lock_actions as la


def by_name(pairs: set[tuple[str, str]]) -> dict[str, frozenset[str]]:
    names: dict[str, set[str]] = defaultdict(set)
    for name, version in pairs:
        names[name].add(version)
    return {n: frozenset(v) for n, v in names.items()}


def highest(versions: frozenset[str]) -> str:
    return max(versions, key=la._order)


def divergent_choice(b: frozenset, lo: frozenset, up: frozenset, m: frozenset) -> str:
    """What the maintainer kept of a package both sides changed differently."""
    if m - (b | lo | up):
        return "a version no side had"
    if not m:
        return "removed it"
    if m == lo:
        return "local's"
    if m == up:
        return "upstream's"
    if m == b:
        return "the base's"
    if m == lo | up:
        return "both sides'"
    return "another mix"


def one_sided_choice(b: frozenset, changed: frozenset, m: frozenset) -> str:
    if m == changed:
        return "took the change"
    if m == b:
        return "kept the base"
    if m - (b | changed):
        return "a version no side had"
    return "another mix"


study, hosts, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
rows = []
for line in (study / "labels.jsonl").read_text().splitlines():
    label = json.loads(line)
    c = cases[label["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in label["files"]:
        path = f["path"]
        done = {r["action"]: r["reproduces"] for r in f["results"]}
        sides = {}
        for side in ("base", "first", "second", "merge"):
            text = la._show(repo, c[side], path)
            sides[side] = by_name((la.packages(path, text) if text is not None else None) or set())
        b, lo, up, mm = sides["base"], sides["first"], sides["second"], sides["merge"]
        empty: frozenset[str] = frozenset()
        kinds: Counter[str] = Counter()
        divergent, one_sided = [], []
        names: set[str] = set()  # kept in memory only: no package name is written out
        for name in sorted(set(b) | set(lo) | set(up) | set(mm)):
            vb, vl, vu, vm = (s.get(name, empty) for s in (b, lo, up, mm))
            if name not in b and name not in lo and name not in up:
                kinds["added in the merge"] += 1
                continue
            cl, cu = vl != vb, vu != vb
            if not cl and not cu:
                kinds["untouched"] += 1
                if vm != vb:
                    kinds["untouched, changed in the merge"] += 1
            elif cl != cu:
                kinds["one-sided"] += 1
                one_sided.append(one_sided_choice(vb, vl if cl else vu, vm))
            elif vl == vu:
                kinds["convergent"] += 1
            else:
                kinds["divergent"] += 1
                names.add(name)
                choice = divergent_choice(vb, vl, vu, vm)
                both = vl | vu
                top = highest(both) if both else None
                divergent.append(
                    {
                        "choice": choice,
                        "highest": bool(top) and vm == frozenset({top}),
                        "single_each": len(vl) == 1 and len(vu) == 1,
                    }
                )
        pairs = {side: {(n, v) for n, vs in s.items() for v in vs} for side, s in sides.items()}
        merged = la.three_way(pairs["base"], pairs["first"], pairs["second"])
        if eu.predicted(path) == "three_way_unified":
            merged = la.unify(path, merged)
        rest = {p for p in merged if p[0] not in names}
        target = pairs["merge"]
        tie_breaks = {}
        for rule in ("local", "upstream", "highest"):
            chosen = set()
            for n in names:
                vl, vu = lo.get(n, empty), up.get(n, empty)
                if rule == "local":
                    pick = vl
                elif rule == "upstream":
                    pick = vu
                else:
                    pick = frozenset({highest(vl | vu)}) if vl | vu else empty
                chosen |= {(n, v) for v in pick}
            tie_breaks[rule] = rest | chosen == target
        rows.append(
            {
                "study": study.name,
                "index": label["index"],
                "repo": c["repo"],
                "path": path,
                "family": eu.family(path),
                "predicted_reproduces": done[eu.predicted(path)],
                "any_reproduces": any(done.values()),
                "new_versions": sum(
                    len(vm - (b.get(n, empty) | lo.get(n, empty) | up.get(n, empty)))
                    for n, vm in mm.items()
                ),
                "packages": len(mm),
                "kinds": dict(kinds),
                "divergent": divergent,
                "outside_divergent": rest == {p for p in target if p[0] not in names},
                "recomputed_reproduces": merged == target,
                "tie_breaks": tie_breaks,
                "one_sided": dict(Counter(one_sided)),
            }
        )
out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
print(study.name, len(rows), "conflicted files")
