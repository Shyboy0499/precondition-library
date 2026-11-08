"""Did `git archive` leave files out of the trees the ecosystems' tools ran in? (#336, #297)

Two earlier results ran a tool in the merge's tree, extracted with `git archive`:

- `results/lock-actions-2026-10-27/`: the `reconcile_*` and `regenerate` actions on stage A's 30
  conflicts (`lock_actions._checkout`);
- `results/lock-tool-dated-2026-11-03/`: dated npm on studies 3 and 4's unreproduced
  `package-lock.json` files (`npm_dated.py`).

`git archive` applies the repository's own attributes: `export-ignore` leaves a file out and
`export-subst` rewrites `$Format:...$` placeholders. A maintainer merging in a working tree has
every file as committed. For each merge those results ran a tool in, this lists the blobs the
archive dropped and the files it changed, comparing `git archive` with `git ls-tree`.

    python results/archive-attributes-2026-11-08/audit.py <out.jsonl> \\
        stage-A=<stage dir>:<its cases' repository cache> \\
        study-3=<study dir>:<cache> study-4=<study dir>:<cache>

A repository missing from a cache is fetched there, one commit at a time (`--depth=1`).
"""

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

LOCKS = ("package-lock.json", "Cargo.lock", "poetry.lock", "yarn.lock")
MANIFESTS = {
    "package.json",
    ".npmrc",
    "npm-shrinkwrap.json",
    "Cargo.toml",
    "pyproject.toml",
    "poetry.toml",
    ".yarnrc",
    ".yarnrc.yml",
    "rust-toolchain",
    "rust-toolchain.toml",
}


def git(repo: Path, *argv: str, text: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *argv], capture_output=True, text=text, check=True
    ).stdout


def repository(cache: Path, repo: str, sha: str) -> Path:
    """`<cache>/<owner>__<name>.git` when the study's own cache does not hold the commit."""
    path = cache / (repo.replace("/", "__") + ".git")
    if not path.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(path)], check=True)
        git(path, "remote", "add", "origin", f"https://github.com/{repo}.git")
    if subprocess.run(
        ["git", "-C", str(path), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True
    ).returncode:
        git(path, "fetch", "-q", "--depth=1", "--no-tags", "origin", sha)
    return path


def compare(repo: Path, commit: str) -> dict:
    blobs = {}
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split("\0"):
        if record:
            meta, name = record.split("\t", 1)
            if meta.split(" ")[1] == "blob":
                blobs[name] = meta.split(" ")[2]
    archive = git(repo, "archive", "--format=tar", commit, text=False)
    archived = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                archived[member.name] = tar.extractfile(member).read()
    dropped = sorted(set(blobs) - set(archived))
    changed = sorted(
        name
        for name, content in archived.items()
        if name in blobs and not name.endswith("/")
        and content != git(repo, "cat-file", "blob", blobs[name], text=False)
        and b"$Format" in git(repo, "cat-file", "blob", blobs[name], text=False)
    )  # fmt: skip
    return {"dropped": dropped, "changed": changed}


def main() -> None:
    out = Path(sys.argv[1])
    rows = []
    for spec in sys.argv[2:]:
        name, paths = spec.split("=", 1)
        study, cache = (Path(p) for p in paths.split(":", 1))
        cache.mkdir(parents=True, exist_ok=True)
        manifest = json.loads((study / "manifest.json").read_text())
        labels = (
            Path("results/lock-actions-2026-10-27/stage-A.jsonl")
            if name == "stage-A"
            else study / "labels.jsonl"
        )
        tips = {r["repo"]: r["tip"] for r in manifest.get("repositories", [])}
        cases = {c["index"]: c for c in manifest["cases"]}
        for line in labels.read_text().splitlines():
            row = json.loads(line)
            if name == "stage-A":
                files = [f["path"] for f in row["files"]
                         if any(r["action"].startswith(("reconcile", "regenerate"))
                                for r in f["results"])]  # fmt: skip
            else:  # the npm pilot's files: package-lock.json no computed action reproduced
                files = [f["path"] for f in row["files"]
                         if f["path"].endswith("package-lock.json")
                         and not any(r["reproduces"] for r in f["results"])]  # fmt: skip
            if not files:
                continue
            case = cases[row["index"]]
            cached = cache / f"{tips.get(case['repo'], '')}-1000000.git"
            repo = cached if cached.exists() else repository(cache, case["repo"], case["merge"])
            found = compare(repo, case["merge"])
            folders = {f.rsplit("/", 1)[0] if "/" in f else "" for f in files}
            read = [
                p for p in found["dropped"] + found["changed"]
                if p.rsplit("/", 1)[-1] in MANIFESTS or p.rsplit("/", 1)[-1] in LOCKS
            ]  # fmt: skip
            result = {
                "study": name,
                "index": row["index"],
                "repo": case["repo"],
                "lock_files": files,
                "lock_folders": sorted(folders),
                "dropped": len(found["dropped"]),
                "changed": len(found["changed"]),
                "manifests_dropped_or_changed": read,
            }
            rows.append(result)
            if found["dropped"] or found["changed"]:
                print(json.dumps(result), flush=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    for name in sorted({r["study"] for r in rows}):
        mine = [r for r in rows if r["study"] == name]
        print(
            name,
            "cases:", len(mine),
            "with files dropped or changed:", sum(1 for r in mine if r["dropped"] or r["changed"]),
            "with a manifest or lock file dropped or changed:",
            sum(1 for r in mine if r["manifests_dropped_or_changed"]),
        )  # fmt: skip


if __name__ == "__main__":
    main()
