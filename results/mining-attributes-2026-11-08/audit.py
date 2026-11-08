"""Did repositories' `.gitattributes` change any case of studies 1, 3, 4 or 5? (#306, a validity
check after study 5.)

Study 1's mining (`real_merges.mine`), which every lock-file study since has shared, runs
`git merge-tree` in a cache with no checked-out HEAD, so no repository's `.gitattributes` applies.
A maintainer merging in a working tree gets them. Of the attributes, `merge` changes a merge: a
lock file declared `binary` (or `-merge`) conflicts whenever both sides changed it, and
`merge=<driver>` hands it to a custom driver.

For every case in a study's `manifest.json`, this asks git for the `merge` attribute of each lock
file the case turns on. For a positive, that is each conflicted lock file. For a negative (a clean
merge), it is each lock file both sides changed. Attributes are read from the case's first parent,
the tree the maintainer merged into:

    git check-attr --source=<first parent> merge -- <path>

    python results/mining-attributes-2026-11-08/audit.py <study> <caches> <clones> <out.jsonl>

A repository found in `<caches dir>` as `<tip>-1000000.git` (the studies' own caches) is used as
it is. Otherwise it is cloned bare and blobless into `<clones dir>`, and `git check-attr` fetches
only the `.gitattributes` blobs it reads. Nothing here reads a lock file's contents.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

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


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True
    ).stdout


def is_lock(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in LOCK_FILES


def repository(repo: str, tip: str, caches: Path, clones: Path) -> Path:
    cached = caches / f"{tip}-1000000.git"
    if cached.exists():
        return cached
    clone = clones / (repo.replace("/", "__") + ".git")
    if not clone.exists():
        subprocess.run(
            ["git", "clone", "-q", "--bare", "--filter=blob:none", "--no-tags",
             f"https://github.com/{repo}.git", str(clone)],
            check=True,
        )  # fmt: skip
    if subprocess.run(["git", "-C", str(clone), "cat-file", "-e", tip]).returncode:
        git(clone, "fetch", "-q", "--filter=blob:none", "origin", tip)
    return clone


def changed_locks(repo: Path, base: str, side: str) -> set[str]:
    names = git(repo, "diff", "--no-renames", "--name-only", base, side).splitlines()
    return {path for path in names if is_lock(path)}


def main() -> None:
    study, caches, clones, out = (Path(a) for a in sys.argv[1:5])
    clones.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((study / "manifest.json").read_text())
    tips = {r["repo"]: r["tip"] for r in manifest["repositories"]}
    rows, tally = [], Counter()
    for case in manifest["cases"]:
        repo = repository(case["repo"], tips[case["repo"]], caches, clones)
        if case["kind"] == "positive":
            paths = sorted(p for p in case["conflicted"] if is_lock(p))
        else:
            paths = sorted(
                changed_locks(repo, case["base"], case["first"])
                & changed_locks(repo, case["base"], case["second"])
            )
        found = {}
        for path in paths:
            line = git(repo, "check-attr", f"--source={case['first']}", "merge", "--", path)
            found[path] = line.rsplit(": ", 1)[-1].strip()
        set_ = {p: v for p, v in found.items() if v != "unspecified"}
        tally[(case["kind"], "attribute set" if set_ else "none")] += 1
        rows.append(
            {
                "index": case["index"],
                "repo": case["repo"],
                "kind": case["kind"],
                "merge_attribute": found,
            }
        )
        if set_:
            print(case["index"], case["repo"], case["kind"], set_, flush=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(study.name, {f"{k} / {s}": v for (k, s), v in sorted(tally.items())})


if __name__ == "__main__":
    main()
