"""Pilot (exploratory, seen data): the per-ecosystem merge T, then only the packages the merged
manifest still reaches through the lock files' own dependency edges.

composer.lock (roots: composer.json require + require-dev) and package-lock.json formats 2 and 3
(roots: package.json's four dependency maps; repositories with workspaces are skipped). An edge
from a package is read from whichever of base, local and upstream lock files holds that exact
(package, version). Platform requirements (php, ext-*, lib-*, composer-*) are not packages.

    PYTHONPATH=src python closure.py <study> <its real-hosts cache>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

PLATFORM = ("php", "ext-", "lib-", "composer-", "hhvm")
study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}


def edges_composer(text):
    out = {}
    for sec in ("packages", "packages-dev"):
        for p in json.loads(text).get(sec) or []:
            # Composer's names are case-insensitive; a requirement may differ in case.
            req = [n.lower() for n in (p.get("require") or {}) if not n.startswith(PLATFORM)]
            for alias in list(p.get("provide") or {}) + list(p.get("replace") or {}):
                out.setdefault(("@provides", alias.lower()), []).append(p["name"].lower())
            out[(p["name"].lower(), str(p["version"]))] = req
    return out


def edges_npm(text):
    out = {}
    for key, e in (json.loads(text).get("packages") or {}).items():
        if "node_modules/" not in key or "version" not in e or e.get("link"):
            continue
        deps = []
        for sec in ("dependencies", "optionalDependencies", "peerDependencies"):
            deps += list(e.get(sec) or {})
        out[(key.rsplit("node_modules/", 1)[1], str(e["version"]))] = deps
    return out


def roots(manifest_text, kind):
    d = json.loads(manifest_text)
    if kind == "composer":
        secs = ("require", "require-dev")
    else:
        if d.get("workspaces"):
            return None
        secs = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    names = {n for s in secs for n in (d.get(s) or {}) if not n.startswith(PLATFORM)}
    return {n.lower() for n in names} if kind == "composer" else names


count = Counter()
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in row["files"]:
        name = f["path"].rsplit("/", 1)[-1]
        if name == "composer.lock":
            kind, man, edges_of = "composer", "composer.json", edges_composer
        elif name == "package-lock.json":
            kind, man, edges_of = "npm", "package.json", edges_npm
        else:
            continue
        texts = {k: la._show(repo, c[k], f["path"]) for k in ("base", "first", "second", "merge")}
        if texts["merge"] is None or texts["first"] is None or texts["second"] is None:
            continue
        mtext = la._show(repo, c["merge"], f["path"][: -len(name)] + man)
        try:
            r = roots(mtext, kind) if mtext else None
            if kind == "npm" and "packages" not in json.loads(texts["merge"]):
                r = None  # format 1: not covered by this pilot
        except json.JSONDecodeError:
            r = None
        if r is None:
            count["skipped"] += 1
            continue
        sets = {k: la.packages(f["path"], t) or set() if t else set() for k, t in texts.items()}
        t = la.three_way(sets["base"], sets["first"], sets["second"])
        if kind == "composer":
            t = la.unify(f["path"], t)
        edges = {}
        for k in ("base", "first", "second"):
            if texts[k]:
                try:
                    edges.update(edges_of(texts[k]))
                except (json.JSONDecodeError, KeyError):
                    pass
        reach, todo = set(), list(r)
        fold = str.lower if kind == "composer" else str
        by_name = {}
        for n, v in t:
            by_name.setdefault(fold(n), []).append(v)
        while todo:
            n = todo.pop()
            if n in reach:
                continue
            reach.add(n)
            todo += edges.get(("@provides", n), [])  # a provided or replaced name
            for v in by_name.get(n, []):
                todo += edges.get((n, v), [])
        closed = {(n, v) for n, v in t if fold(n) in reach}
        merged = sets["merge"]
        done = {x["action"]: x["reproduces"] for x in f["results"]}
        before = done["three_way_unified" if kind == "composer" else "three_way"]
        after = closed == merged
        count[f"{kind} files"] += 1
        count[f"{kind} merge reproduced"] += before
        count[f"{kind} closed merge reproduces"] += after
        count[f"{kind} gained"] += after and not before
        count[f"{kind} lost"] += before and not after
        count[f"{kind} gained where nothing reproduced"] += after and not any(done.values())
print(study.name, dict(sorted(count.items())))
