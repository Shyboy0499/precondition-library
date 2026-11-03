"""Pilot (exploratory, seen data): npm's own tool, pinned to the merge's date, on the
package-lock.json files no computed action reproduced.

For each such file: the merge's whole tree, with the lock file replaced by one side's, then
`npm install --package-lock-only --ignore-scripts --before=<merge's committer date>`. The
registry answers as it stood that day, so a resolution a maintainer made then can be replayed.
The result's (package, version) set is compared with the maintainer's.

    PYTHONPATH=src python results/lock-tool-dated-2026-11-03/npm_dated.py \\
        <study> <its real-hosts cache> <scratch> [limit] [npm options...]

Arguments starting with `--` are passed on to npm, for example `--engine-strict=false`.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from precondition_library.bench import lock_actions as la

options = [a for a in sys.argv[1:] if a.startswith("--")]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
study, hosts, scratch = Path(args[0]), Path(args[1]), Path(args[2]).resolve()
limit = int(args[3]) if len(args) > 3 else 10**9
m = json.loads((study / "manifest.json").read_text())
tips = {r["repo"]: r["tip"] for r in m["repositories"]}
cases = {c["index"]: c for c in m["cases"]}
count = Counter()
rows = []
for line in (study / "labels.jsonl").read_text().splitlines():
    row = json.loads(line)
    c = cases[row["index"]]
    for f in row["files"]:
        if f["path"].endswith("package-lock.json") and not any(
            r["reproduces"] for r in f["results"]
        ):
            rows.append((row, c, f))
for row, c, f in rows[:limit]:
    repo = hosts / f"{tips[c['repo']]}-1000000.git"
    when = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%cI", c["merge"]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    merged = la.packages(f["path"], la._show(repo, c["merge"], f["path"]) or "") or set()
    outcome = {}
    for side in ("first", "second"):
        start = la._show(repo, c[side], f["path"])
        with tempfile.TemporaryDirectory(dir=scratch) as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            archive = subprocess.run(
                ["git", "-C", str(repo), "archive", "--format=tar", c["merge"]],
                capture_output=True,
                check=True,
            ).stdout
            subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
            lock = tree / f["path"]
            if start is None:
                lock.unlink(missing_ok=True)
            else:
                lock.write_text(start)
            try:
                ran = subprocess.run(
                    [
                        "npm",
                        "install",
                        "--package-lock-only",
                        "--ignore-scripts",
                        "--no-audit",
                        "--no-fund",
                        f"--before={when}",
                        *options,
                    ],
                    cwd=lock.parent,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env={**os.environ, "npm_config_cache": str(scratch / "cache")},
                )
                got = la.packages(f["path"], lock.read_text()) if ran.returncode == 0 else None
                if ran.returncode != 0:
                    error = [x for x in ran.stderr.splitlines() if x.startswith("npm error code")]
                    print("  ", side, *error[:1], flush=True)
            except subprocess.TimeoutExpired:
                got = None
            outcome[side] = (
                "failed"
                if got is None
                else (
                    "reproduces"
                    if got == merged
                    else f"jaccard {len(got & merged) / len(got | merged):.3f}"
                )
            )
    count["files"] += 1
    count["reproduced from some side"] += any(v == "reproduces" for v in outcome.values())
    count["tool failed on both sides"] += all(v == "failed" for v in outcome.values())
    print(row["index"], c["repo"], f["path"], when[:10], outcome, flush=True)
print(study.name, dict(count))
