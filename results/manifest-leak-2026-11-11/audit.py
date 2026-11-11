"""Did the ecosystem's check see the maintainer's answer? (#297, study 6)

Study 6 and `results/lock-tool-check-2026-11-08/` judge each side's lock file in the merge's
tree, as committed (tool-precondition §4). That tree holds the maintainer's resolution of every
other file, the manifests included. A resolver at merge time does not have it. It has git's own
merge of the two sides, where the files beside the lock file merged cleanly, and nothing where
they conflicted.

For every checked lock file this compares the files the check reads, in the merge's tree and in
git's merge of the two parents (`git merge-tree --write-tree --merge-base=<base>`). The lock
file itself is not compared. Each file is put in one class:

- **same:** every file the check reads is git's merge, so the recorded verdicts are the ones a
  resolver at merge time would get;
- **conflicted:** git reports a conflict in one of them, so a resolver has no manifest to
  check against. (In one file git reports a conflict and still writes the maintainer's blob;
  it counts as conflicted.)
- **edited:** git merged them all, and the maintainer committed something else in at least one.

The files the check reads, under the lock file's folder (any depth, `node_modules` and
`vendor` aside):
- npm: `package.json`, `.npmrc`, `npm-shrinkwrap.json`;
- pnpm: `package.json`, `.npmrc`, `pnpm-workspace.yaml`, `.pnpmfile.cjs`;
- Composer: `composer.json` and `auth.json` in the folder itself.
That is a superset of what each tool reads for a workspace, so "same" is conservative.

    python results/manifest-leak-2026-11-11/audit.py <out.jsonl> <cache> \\
        study-6=results/tool-precondition-2026-11-09 \\
        study-3=results/lock-oracle-2026-11-02:$CHECKED/study-3.jsonl \\
        study-4=results/ecosystem-unify-2026-11-02:$CHECKED/study-4.jsonl \\
        study-5=results/divergence-gate-2026-11-08:$CHECKED/study-5.jsonl

with `CHECKED=results/lock-tool-check-2026-11-08`.

Each argument names a study, the directory holding its `manifest.json`, and, after a colon, its
checked files (by default `files.jsonl` in that directory).

No path or package name is written: only counts.
"""

import json
import posixpath
import subprocess
import sys
from pathlib import Path

READS = {
    "npm": {"package.json", ".npmrc", "npm-shrinkwrap.json"},
    "pnpm": {"package.json", ".npmrc", "pnpm-workspace.yaml", ".pnpmfile.cjs"},
    "composer": {"composer.json", "auth.json"},
}
SKIP = ("node_modules/", "vendor/")


def git(repo: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=True, check=check
    )


def repository(cache: Path, repo: str, shas: list[str]) -> Path:
    """`<cache>/<owner>__<name>.git`, holding each commit at depth 1, blobs on demand."""
    path = cache / (repo.replace("/", "__") + ".git")
    if not path.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
        git(path, "remote", "add", "origin", f"https://github.com/{repo}.git")
        git(path, "config", "remote.origin.promisor", "true")
        git(path, "config", "remote.origin.partialclonefilter", "blob:none")
    missing = [
        s for s in shas if git(path, "cat-file", "-e", f"{s}^{{commit}}", check=False).returncode
    ]
    if missing:
        git(path, "fetch", "-q", "--depth=1", "--no-tags", "--filter=blob:none", "origin", *missing)
    return path


def entries(repo: Path, tree: str) -> dict[str, str]:
    """Every blob in the tree: path to object id."""
    out = git(repo, "ls-tree", "-r", "-z", "--full-tree", tree).stdout
    found = {}
    for record in out.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, kind, oid = meta.split()
        if kind == "blob":
            found[path] = oid
    return found


def reads(paths: set[str], lock: str, tool: str) -> set[str]:
    folder = posixpath.dirname(lock)
    prefix = f"{folder}/" if folder else ""
    chosen = set()
    for path in paths:
        if not path.startswith(prefix) or path == lock:
            continue
        rest = path[len(prefix) :]
        if any(part in f"/{rest}" for part in ("/" + s for s in SKIP)) or rest.startswith(SKIP):
            continue
        name = posixpath.basename(rest)
        if name not in READS[tool]:
            continue
        if tool == "composer" and "/" in rest:
            continue
        chosen.add(path)
    return chosen


def audit(study: str, directory: Path, files: Path, cache: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    cases = {(c["repo"], c["index"]): c for c in manifest["cases"]}
    rows = [json.loads(line) for line in files.read_text("utf-8").splitlines()]
    merged: dict[tuple[str, int], tuple[str, set[str]]] = {}
    found = []
    for row in rows:
        case = cases[(row["repo"], row["index"])]
        shas = [case["merge"], case["first"], case["second"], case["base"]]
        repo = repository(cache, row["repo"], shas)
        key = (row["repo"], row["index"])
        if key not in merged:
            ran = git(
                repo, "merge-tree", "--write-tree", "--name-only", "--no-messages",
                f"--merge-base={case['base']}", case["first"], case["second"], check=False,
            )  # fmt: skip
            if ran.returncode not in (0, 1):
                raise SystemExit(f"merge-tree failed on {key}: {ran.stderr.strip()}")
            lines = ran.stdout.split("\n")
            merged[key] = (lines[0], {x for x in lines[1:] if x})
        tree, conflicted = merged[key]
        committed = entries(repo, case["merge"])
        auto = entries(repo, tree)
        inputs = reads(set(committed) | set(auto), row["path"], row["tool"])
        differ = {p for p in inputs if committed.get(p) != auto.get(p)}
        if inputs & conflicted:
            kind = "conflicted"
        else:
            kind = "edited" if differ else "same"
        found.append(
            {
                "study": study,
                "repo": row["repo"],
                "index": row["index"],
                "path": row["path"],
                "tool": row["tool"],
                "inputs": len(inputs),
                "differ": len(differ),
                "conflicted_inputs": len(inputs & conflicted),
                "class": kind,
            }
        )
        print(study, row["repo"], row["index"], kind, file=sys.stderr)
    return found


def main() -> None:
    out, cache = Path(sys.argv[1]), Path(sys.argv[2])
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in sys.argv[3:]:
        study, where = spec.split("=", 1)
        directory, _, files = where.partition(":")
        listed = Path(files) if files else Path(directory) / "files.jsonl"
        rows += audit(study, Path(directory), listed, cache)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    main()
