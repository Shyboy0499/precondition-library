"""Build the lock-file conflicts dataset from this repository's committed study manifests.

Every positive case of studies 1 and 3-6 whose conflicted files include a lock file becomes one
row: the repository, the four commits (merge base, both parents, the maintainer's merge), the
lock file's path, and labels computed from the four versions of that file:

- which simple action gives the maintainer's resolved packages (`reproduces`), read as sets of
  `(package, version)` pairs, exactly as studies 3-5 compared them (`lock_actions.packages`);
- how many packages the two sides changed, and how many they changed differently;
- for `package-lock.json` and `composer.lock`, what lockmerge did and whether the result is
  valid for the maintainer's merged manifest (as `results/lockmerge-2026-11-25/`).

Only commits, paths and derived labels are written: no file content from any repository. The
four versions are fetched by commit from `raw.githubusercontent.com` into `--cache`.

    PYTHONPATH=src:lockmerge/src python datasets/lockfile-conflicts/build.py --cache DIR
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import sys
import threading
from pathlib import Path, PurePosixPath
from typing import Any

import lockmerge
from lockmerge import Merged
from precondition_library.studies.lock_actions import READERS, packages, three_way, unify

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "results" / "lockmerge-2026-11-25"))
from evaluate import fetch as _fetch_unsafe  # noqa: E402  (the replay's fetcher)
from evaluate import valid  # noqa: E402  (and its validity check)

_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def fetch(cache: Path, repo: str, commit: str, path: str) -> str | None:
    """The replay's fetcher, one thread per file: two rows can share a file, and a thread must
    not read a file another is still writing (the first build of this dataset did, for two
    rows)."""
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault((repo, commit, path), threading.Lock())
    with lock:
        return _fetch_unsafe(cache, repo, commit, path)


MANIFESTS = {
    "study-1-stage-A": "results/real-merges-2026-10-26/stage-A/manifest.json",
    "study-1-stage-B": "results/real-merges-2026-10-26/stage-B/manifest.json",
    "study-3": "results/lock-oracle-2026-11-02/manifest.json",
    "study-4": "results/ecosystem-unify-2026-11-02/manifest.json",
    "study-5": "results/divergence-gate-2026-11-08/manifest.json",
    "study-6": "results/tool-precondition-2026-11-09/manifest.json",
}
ECOSYSTEM = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "composer.lock": "composer",
    "Gemfile.lock": "bundler",
    "Cargo.lock": "cargo",
    "poetry.lock": "poetry",
    "Pipfile.lock": "pipenv",
    "uv.lock": "uv",
}


def cases() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    repositories: dict[str, dict[str, Any]] = {}
    for study, manifest in MANIFESTS.items():
        data = json.loads((ROOT / manifest).read_text(encoding="utf-8"))
        for repository in data["repositories"]:
            repositories.setdefault(repository["repo"], repository)
        for case in data["cases"]:
            if case.get("kind") != "positive":
                continue
            conflicted = list(case.get("conflicted") or [])
            for path in conflicted:
                if PurePosixPath(path).name not in READERS:
                    continue
                key = (case["repo"], case["merge"], path)
                row = rows.setdefault(
                    key,
                    {
                        "repo": case["repo"],
                        "path": path,
                        "lock_file": PurePosixPath(path).name,
                        "merge": case["merge"],
                        "base": case["base"],
                        "ours": case["first"],
                        "theirs": case["second"],
                        "other_conflicted_files": sorted(p for p in conflicted if p != path),
                        "studies": [],
                    },
                )
                if study not in row["studies"]:
                    row["studies"].append(study)
    ordered = sorted(rows.values(), key=lambda r: (r["repo"], r["merge"], r["path"]))
    return ordered, repositories


def _by_name(found: set[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    names: dict[str, list[str]] = {}
    for name, version in found:
        names.setdefault(name, []).append(version)
    return {name: tuple(sorted(v)) for name, v in names.items()}


def _sets(path: str, texts: dict[str, str]) -> dict[str, set[tuple[str, str]]] | None:
    try:
        out = {side: packages(path, text) if text else set() for side, text in texts.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if any(v is None for v in out.values()):
        return None
    return out  # type: ignore[return-value]


def label(row: dict[str, Any], cache: Path) -> dict[str, Any]:
    path, repo = row["path"], row["repo"]
    texts = {s: fetch(cache, repo, row[s], path) for s in ("base", "ours", "theirs", "merge")}
    out = dict(row)
    out["id"] = f"{repo}@{row['merge'][:12]}:{path}"
    out["ecosystem"] = ECOSYSTEM[row["lock_file"]]
    if any(t is None for t in texts.values()):
        out["maintainer_file"] = "unreachable"
        return out
    merged = texts["merge"] or ""
    if not merged:
        out["maintainer_file"] = "deleted"
        return out
    if "<<<<<<<" in merged or ">>>>>>>" in merged:
        out["maintainer_file"] = "conflict markers"
        return out
    out["maintainer_file"] = "present"
    sets = _sets(path, {k: v or "" for k, v in texts.items()})
    if sets is None:
        out["maintainer_file"] = "unreadable"
        return out
    b, o, t, m = sets["base"], sets["ours"], sets["theirs"], sets["merge"]
    combined = three_way(b, o, t)
    out["reproduces"] = {
        "take_ours": o == m,
        "take_theirs": t == m,
        "three_way": combined == m,
        "three_way_unified": unify(path, combined) == m,
    }
    nb, no, nt = _by_name(b), _by_name(o), _by_name(t)
    changed_ours = {n for n in set(nb) | set(no) if nb.get(n) != no.get(n)}
    changed_theirs = {n for n in set(nb) | set(nt) if nb.get(n) != nt.get(n)}
    both = changed_ours & changed_theirs
    out["packages_changed"] = {"ours": len(changed_ours), "theirs": len(changed_theirs)}
    out["packages_diverged"] = sum(1 for n in both if no.get(n) != nt.get(n))
    out["maintainer_versions_new"] = len(m - o - t)
    if lockmerge.supported(path):
        manifest_name = "composer.json" if row["lock_file"] == "composer.lock" else "package.json"
        manifest = fetch(
            cache, repo, row["merge"], str(PurePosixPath(path).with_name(manifest_name))
        )
        out["maintainer_valid"] = valid(path, merged, manifest)
        project = manifest if row["lock_file"] == "composer.lock" else None
        result = {}
        for mode, given in (("driver", None), ("resolve", project)):
            outcome = lockmerge.merge(
                path,
                texts["base"] or "",
                texts["ours"] or "",
                texts["theirs"] or "",
                composer_json=given,
            )
            if isinstance(outcome, Merged):
                result[mode] = {
                    "merged": True,
                    "valid": valid(path, outcome.text, manifest),
                    "same_packages": _sets(path, {"x": outcome.text})["x"] == m  # type: ignore[index]
                    if _sets(path, {"x": outcome.text})
                    else None,
                }
            else:
                result[mode] = {"merged": False, "declined": outcome.reasons[:3]}
        out["lockmerge_0_1_0"] = result
    return out


FIELDS = [
    "id",
    "ecosystem",
    "lock_file",
    "repo",
    "path",
    "merge",
    "base",
    "ours",
    "theirs",
    "maintainer_file",
    "packages_diverged",
    "maintainer_versions_new",
    "reproduces_take_ours",
    "reproduces_take_theirs",
    "reproduces_three_way",
    "reproduces_three_way_unified",
    "lockmerge_driver_merged",
    "lockmerge_driver_valid",
    "studies",
    "licence",
]


def flat(row: dict[str, Any], repositories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reproduces = row.get("reproduces") or {}
    driver = (row.get("lockmerge_0_1_0") or {}).get("driver") or {}
    return {
        "id": row["id"],
        "ecosystem": row["ecosystem"],
        "lock_file": row["lock_file"],
        "repo": row["repo"],
        "path": row["path"],
        "merge": row["merge"],
        "base": row["base"],
        "ours": row["ours"],
        "theirs": row["theirs"],
        "maintainer_file": row["maintainer_file"],
        "packages_diverged": row.get("packages_diverged", ""),
        "maintainer_versions_new": row.get("maintainer_versions_new", ""),
        **{
            f"reproduces_{k}": reproduces.get(k, "")
            for k in ("take_ours", "take_theirs", "three_way", "three_way_unified")
        },
        "lockmerge_driver_merged": driver.get("merged", ""),
        "lockmerge_driver_valid": driver.get("valid", ""),
        "studies": ";".join(row["studies"]),
        "licence": repositories.get(row["repo"], {}).get("licence", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()
    rows, repositories = cases()
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        labelled = list(pool.map(lambda r: label(r, args.cache), rows))
    with (HERE / "conflicts.jsonl").open("w", encoding="utf-8") as out:
        for row in labelled:
            row["licence"] = repositories.get(row["repo"], {}).get("licence", "")
            row["repo_url"] = f"https://github.com/{row['repo']}"
            out.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    with (HERE / "conflicts.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in labelled:
            writer.writerow(flat(row, repositories))
    print(f"{len(labelled)} conflicts from {len({r['repo'] for r in labelled})} repositories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
