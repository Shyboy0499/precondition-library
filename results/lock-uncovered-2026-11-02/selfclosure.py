"""Sanity check for a manifest-aware merge (exploratory): on the maintainer's own merged
composer.lock, how many packages are reachable from the merged composer.json's require and
require-dev through the lock's own `require` edges (names folded to lower case, provide and
replace honoured)? A closure that drops packages the maintainer kept cannot be the
maintainer's rule.

    PYTHONPATH=src python selfclosure.py <study> <its real-hosts cache>
"""

import json
import sys
from pathlib import Path

from precondition_library.bench import lock_actions as la

PLATFORM = ("php", "ext-", "lib-", "composer-", "hhvm")
study, hosts = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
files = whole = 0
shares = []
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    for f in row["files"]:
        if not f["path"].endswith("composer.lock"):
            continue
        lock = la._show(repo, c["merge"], f["path"])
        manifest = la._show(repo, c["merge"], f["path"][: -len("composer.lock")] + "composer.json")
        try:
            d, man = json.loads(lock), json.loads(manifest)
        except (TypeError, json.JSONDecodeError):
            continue
        pk = [p for s in ("packages", "packages-dev") for p in d.get(s) or []]
        edges = {
            p["name"].lower(): [
                n.lower() for n in p.get("require") or {} if not n.startswith(PLATFORM)
            ]
            for p in pk
        }
        provides: dict[str, list[str]] = {}
        for p in pk:
            for alias in list(p.get("provide") or {}) + list(p.get("replace") or {}):
                provides.setdefault(alias.lower(), []).append(p["name"].lower())
        todo = [
            n.lower()
            for s in ("require", "require-dev")
            for n in man.get(s) or {}
            if not n.startswith(PLATFORM)
        ]
        reach: set[str] = set()
        while todo:
            n = todo.pop()
            if n not in reach:
                reach.add(n)
                todo += provides.get(n, []) + edges.get(n, [])
        files += 1
        whole += set(edges) <= reach
        shares.append(len(set(edges) & reach) / len(edges) if edges else 1.0)
shares.sort()
print(
    f"{study.name}: {files} merged composer.lock files; fully reachable from composer.json: "
    f"{whole}; median share reachable {shares[len(shares) // 2]:.3f}"
)
