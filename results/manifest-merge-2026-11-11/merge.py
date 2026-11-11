"""Can a resolver merge the manifests itself, and get the maintainer's? (#297; exploratory)

`results/manifest-leak-2026-11-11/` found that, on 380 of the 1,005 lock files studies 3–6
checked, git reported a conflict in a file the check reads. There a resolver at merge time has
no manifest to check the lock file against. The recorded verdicts used the maintainer's.

Manifests are package maps too. This merges each conflicted `package.json` and `composer.json`
key by key, three ways: a key both sides changed to different values is a conflict, and
anything else takes the side that changed it. It then asks whether the result is the
maintainer's committed manifest, as parsed JSON (key order aside; the checks ignore it). Each
conflicted lock file gets one class:

- **recovered:** every conflicted file the check reads merges key by key to the maintainer's
  committed file, and every other file it reads is git's merge. A resolver that merges the
  manifests this way and then runs the check gets exactly the recorded verdicts;
- **differs:** the key-level merge succeeds, but some file is not the maintainer's. The check
  would run on another manifest, and its verdicts were not computed;
- **unmerged:** some conflicted file cannot be merged this way, because a key changed on both
  sides, a file is not JSON, or a file is not a manifest (`.npmrc`, `pnpm-workspace.yaml`).

For npm and pnpm, the root manifest's own `version` is set aside first: their checks ignore it
(npm 10.9.4 and pnpm 10.28.0, tested in the README), so a resolver may take either side's. A
workspace package's `version` is not set aside.

    cd results/manifest-merge-2026-11-11 && python -I merge.py <cache> > classes.jsonl

`<cache>` is `audit.py`'s cache, which already holds every case's four commits. Imports nothing
from the project. Writes counts and classes, no path beyond the lock file and no package name.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEAK = ROOT / "results" / "manifest-leak-2026-11-11"
STUDIES = {
    "study-6": ROOT / "results" / "tool-precondition-2026-11-09",
    "study-3": ROOT / "results" / "lock-oracle-2026-11-02",
    "study-4": ROOT / "results" / "ecosystem-unify-2026-11-02",
    "study-5": ROOT / "results" / "divergence-gate-2026-11-08",
}
JSON_MANIFESTS = {"package.json", "composer.json"}
ABSENT = object()


SECTIONS = {
    "name", "version", "description", "type", "license", "private", "workspaces", "engines",
    "packageManager", "scripts", "dependencies", "devDependencies", "peerDependencies",
    "optionalDependencies", "overrides", "resolutions", "pnpm", "require", "require-dev",
    "conflict", "replace", "provide", "suggest", "autoload", "autoload-dev", "repositories",
    "config", "extra", "minimum-stability", "prefer-stable",
}  # fmt: skip


class MergeConflictError(Exception):
    """A key both sides changed to different values; `key` is its top-level section."""

    def __init__(self, key: str = "") -> None:
        self.key = key


def _load_audit():
    spec = importlib.util.spec_from_file_location("leak_audit", LEAK / "audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def merge3(base, ours, theirs):
    """Three-way merge of parsed JSON: dictionaries key by key, everything else whole."""
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    if all(isinstance(x, dict) for x in (ours, theirs)) and (
        base is ABSENT or isinstance(base, dict)
    ):
        base = {} if base is ABSENT else base
        merged = {}
        for key in list(ours) + [k for k in theirs if k not in ours]:
            try:
                value = merge3(
                    base.get(key, ABSENT), ours.get(key, ABSENT), theirs.get(key, ABSENT)
                )
            except MergeConflictError:
                raise MergeConflictError(key) from None
            if value is not ABSENT:
                merged[key] = value
        return merged
    raise MergeConflictError


def _without_version(doc):
    """npm's and pnpm's checks ignore the root manifest's own `version` (README), so a
    resolver may take either side's; it is set aside before merging and comparing."""
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != "version"}
    return doc


def blob(audit, repo: Path, commit: str, path: str):
    ran = audit.git(repo, "show", f"{commit}:{path}", check=False)
    if ran.returncode:
        return ABSENT
    return json.loads(ran.stdout)


def classify(audit, cache: Path, study: str, case: dict, lock: str, tool: str) -> dict:
    repo = audit.repository(
        cache, case["repo"], [case[k] for k in ("merge", "first", "second", "base")]
    )
    ran = audit.git(
        repo, "merge-tree", "--write-tree", "--name-only", "--no-messages",
        f"--merge-base={case['base']}", case["first"], case["second"], check=False,
    )  # fmt: skip
    lines = ran.stdout.split("\n")
    tree, conflicted = lines[0], {x for x in lines[1:] if x}
    committed = audit.entries(repo, case["merge"])
    auto = audit.entries(repo, tree)
    inputs = audit.reads(set(committed) | set(auto), lock, tool)
    clashing = inputs & conflicted
    others_differ = any(committed.get(p) != auto.get(p) for p in inputs - clashing)
    found, section, set_aside = "recovered", "", False
    root = f"{lock.rsplit('/', 1)[0]}/package.json" if "/" in lock else "package.json"
    for path in sorted(clashing):
        if path.rsplit("/", 1)[-1] not in JSON_MANIFESTS:
            found, section = "unmerged", "not a JSON manifest"
            break
        try:
            sides = [blob(audit, repo, case[k], path) for k in ("base", "first", "second")]
            mine = blob(audit, repo, case["merge"], path)
            if tool in ("npm", "pnpm") and path == root:
                set_aside = any(isinstance(x, dict) and "version" in x for x in sides)
                sides, mine = [_without_version(x) for x in sides], _without_version(mine)
            merged = merge3(*sides)
        except MergeConflictError as clash:
            found = "unmerged"
            section = clash.key if clash.key in SECTIONS else "another key"
            break
        except json.JSONDecodeError:
            found, section = "unmerged", "not valid JSON"
            break
        if merged != mine:
            found = "differs"
    if found == "recovered" and others_differ:
        found = "differs"
    return {
        "conflicted_inputs": len(clashing),
        "class": found,
        "clash": section,
        "root_version_set_aside": set_aside,
    }


def main() -> None:
    audit = _load_audit()
    cache = Path(sys.argv[1])
    manifests = {
        study: {
            c["index"]: c for c in json.loads((d / "manifest.json").read_text("utf-8"))["cases"]
        }
        for study, d in STUDIES.items()
    }
    for line in (LEAK / "inputs.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if row["class"] != "conflicted":
            continue
        case = manifests[row["study"]][row["index"]]
        found = classify(audit, cache, row["study"], case, row["path"], row["tool"])
        print(
            json.dumps({k: row[k] for k in ("study", "repo", "index", "path", "tool")} | found),
            flush=True,
        )


if __name__ == "__main__":
    main()
