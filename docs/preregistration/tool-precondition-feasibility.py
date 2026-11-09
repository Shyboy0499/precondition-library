"""The feasibility count behind `tool-precondition.md`: study 5's count
(`divergence-gate-feasibility.py`), restricted to the lock files the ecosystems' checks judge
(`composer.lock`, `package-lock.json`, `pnpm-lock.yaml`), and recording which of them a
conflict includes.

For one repository, it counts:
- its two-parent merges;
- those where both sides changed the same such lock file since their merge base;
- those whose `git merge-tree` conflict includes one.

It never reads a merge commit's own tree, so it sees no maintainer resolution, and it runs no
tool.

    python -I docs/preregistration/tool-precondition-feasibility.py OWNER/REPO CLONES_DIR [LIMIT]

The clone is bare, blobless and single-branch; `git merge-tree` fetches the blobs it needs.
**The clone has a HEAD, so git applies HEAD's `.gitattributes` to `merge-tree`.** Study 1's
mining applies none (`results/mining-attributes-2026-11-08/`). So a repository that marks a
lock file `binary` counts every such merge as conflicting here, and study 5 found one that
gave 107 here and one case when mined. Its `binary` counts how many conflicts are binary
lock-file conflicts.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

LOCK_FILES = ("composer.lock", "package-lock.json", "pnpm-lock.yaml")


def git(*argv: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr)
    return result


def is_lock(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in LOCK_FILES


def changed_locks(base: str, tip: str, clone: Path) -> set[str]:
    names = git("diff", "--no-renames", "--name-only", base, tip, cwd=clone).stdout
    return {path for path in names.splitlines() if is_lock(path)}


def count(repo: str, clones: Path, limit: int) -> dict[str, object]:
    started = time.time()
    clone = clones / repo.replace("/", "__")
    if not clone.exists():
        url = f"https://github.com/{repo}.git"
        git("clone", "-q", "--bare", "--filter=blob:none", "--single-branch", url, str(clone),
            cwd=clones)  # fmt: skip
    merges = [
        line.split() for line in git("rev-list", "--merges", "--parents", "HEAD", cwd=clone)
        .stdout.splitlines()
    ]  # fmt: skip
    two_parent = [merge for merge in merges if len(merge) == 3]
    candidates = []
    for _, first, second in two_parent:
        base = git("merge-base", first, second, cwd=clone, check=False).stdout.strip()
        if base and changed_locks(base, first, clone) & changed_locks(base, second, clone):
            candidates.append((first, second))
    tally = {name: 0 for name in LOCK_FILES}
    conflicting = includes = binary = 0
    for first, second in candidates[:limit]:
        merged = git("merge-tree", "--write-tree", "--name-only", "-z", "--messages",
                     first, second, cwd=clone, check=False)  # fmt: skip
        if merged.returncode == 1:
            conflicting += 1
            head, _, messages = merged.stdout.partition("\0\0")
            paths = head.split("\0")[1:]
            locks = {path.rsplit("/", 1)[-1] for path in paths if is_lock(path)}
            includes += bool(locks)
            for name in locks:
                tally[name] += 1
            binary += bool(locks) and "binary" in messages.lower()
    return {
        "repo": repo,
        "merges": len(merges),
        "two_parent": len(two_parent),
        "both_changed_lock": len(candidates),
        "conflict_tried": min(len(candidates), limit),
        "conflicting": conflicting,
        "conflict_includes_lock": includes,
        **{f"includes_{name}": n for name, n in tally.items()},
        "binary": binary,
        "secs": round(time.time() - started),
    }


if __name__ == "__main__":
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    print(json.dumps(count(sys.argv[1], Path(sys.argv[2]), limit)), flush=True)
