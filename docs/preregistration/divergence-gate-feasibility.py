"""The feasibility count behind `divergence-gate.md` §11: study 1's count
(`real-merges-feasibility.py`), which also records the family of the lock files a conflict
includes.

For one repository, counts its two-parent merges, those where both sides changed the same lock
file since their merge base, and those whose `git merge-tree` conflict includes a lock file. It
never reads a merge commit's own tree, so it sees no maintainer resolution, and it runs no arm.

    python -I docs/preregistration/divergence-gate-feasibility.py OWNER/REPO CLONES_DIR [LIMIT]

The clone is bare, blobless and single-branch; `git merge-tree` fetches the blobs it needs.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

NPM_FAMILY = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
LOCK_FILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "Gemfile.lock",
    "composer.lock",
)


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
    conflicting = conflict_includes_lock = one_version = npm = 0
    for first, second in candidates[:limit]:
        merged = git("merge-tree", "--write-tree", "--name-only", "-z", first, second,
                     cwd=clone, check=False)  # fmt: skip
        if merged.returncode == 1:
            conflicting += 1
            paths = merged.stdout.split("\0\0", 1)[0].split("\0")[1:]
            locks = {path.rsplit("/", 1)[-1] for path in paths if is_lock(path)}
            conflict_includes_lock += bool(locks)
            one_version += bool(locks - set(NPM_FAMILY))
            npm += bool(locks & set(NPM_FAMILY))
    return {
        "repo": repo,
        "merges": len(merges),
        "two_parent": len(two_parent),
        "both_changed_lock": len(candidates),
        "conflict_tried": min(len(candidates), limit),
        "conflicting": conflicting,
        "conflict_includes_lock": conflict_includes_lock,
        "includes_one_version": one_version,
        "includes_npm_family": npm,
        "secs": round(time.time() - started),
    }


if __name__ == "__main__":
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    print(json.dumps(count(sys.argv[1], Path(sys.argv[2]), limit)), flush=True)
