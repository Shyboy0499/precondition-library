"""Replay every real `package-lock.json` and `composer.lock` conflict this project has mined
through lockmerge, and grade each automatic merge against what the maintainer committed.

Cases come from the committed manifests of studies 1, 3, 4, 5 and 6: every positive case (a
merge whose parents conflict) whose conflicted files include a supported lock file, deduplicated
by repository, merge commit and path. Each case's four versions -- the merge base, the first
parent ("ours"), the second ("theirs") and the maintainer's merge -- are fetched from
`raw.githubusercontent.com` by commit, and cached.

Two modes:

- **driver**: what git's merge driver sees, the lock file's three versions and nothing else.
- **resolve**: as `lockmerge resolve` runs after the manifests are merged. For `composer.lock`
  that means the merged `composer.json` is available; the maintainer's committed one stands in
  for the user's merge of it. For npm the two modes are identical.

Each merge is graded against the maintainer's file: the same resolved `(package, version)` set
(this project's semantic comparison, `lock_actions.packages`), the same JSON, and the same bytes.

    PYTHONPATH=src:lockmerge/src python results/lockmerge-2026-11-25/evaluate.py --cache DIR
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path, PurePosixPath

import lockmerge
from lockmerge import Merged, composer
from lockmerge._semver import satisfies
from precondition_library.studies.lock_actions import packages

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFESTS = (
    "results/real-merges-2026-10-26/stage-A/manifest.json",
    "results/real-merges-2026-10-26/stage-B/manifest.json",
    "results/lock-oracle-2026-11-02/manifest.json",
    "results/ecosystem-unify-2026-11-02/manifest.json",
    "results/divergence-gate-2026-11-08/manifest.json",
    "results/tool-precondition-2026-11-09/manifest.json",
)


def cases() -> list[dict]:
    seen: dict[tuple[str, str, str], dict] = {}
    for manifest in MANIFESTS:
        data = json.loads((ROOT / manifest).read_text(encoding="utf-8"))
        for case in data["cases"]:
            if case.get("kind") != "positive":
                continue
            for path in case.get("conflicted") or []:
                if not lockmerge.supported(path):
                    continue
                key = (case["repo"], case["merge"], path)
                seen.setdefault(
                    key,
                    {
                        "repo": case["repo"],
                        "merge": case["merge"],
                        "base": case["base"],
                        "ours": case["first"],
                        "theirs": case["second"],
                        "path": path,
                        "study": manifest.split("/")[1],
                    },
                )
    return sorted(seen.values(), key=lambda c: (c["repo"], c["merge"], c["path"]))


def fetch(cache: Path, repo: str, commit: str, path: str) -> str | None:
    """The file's text at `commit`, `""` if it did not exist there, `None` if unreachable."""
    target = cache / repo / commit / path
    missing = target.with_name(target.name + ".missing")
    if target.exists():
        return target.read_text(encoding="utf-8")
    if missing.exists():
        return ""
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                body = response.read().decode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            return body
        except urllib.error.HTTPError as error:
            if error.code == 404:
                missing.parent.mkdir(parents=True, exist_ok=True)
                missing.write_text("", encoding="utf-8")
                return ""
            if error.code not in (429, 500, 502, 503, 504):
                return None
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError):
            pass
        time.sleep(2**attempt)
    return None


def _same_set(path: str, a: str, b: str) -> bool | None:
    try:
        left, right = packages(path, a), packages(path, b)
    except (ValueError, KeyError, TypeError):
        return None
    if left is None or right is None:
        return None
    return left == right


def _json_equal(a: str, b: str) -> bool | None:
    try:
        return json.loads(a) == json.loads(b)
    except ValueError:
        return None


def valid(path: str, text: str, manifest: str | None) -> bool | None:
    """Whether a lock file is one its package manager would accept for the merged manifest.

    npm (`npm ci`'s check, done here offline): every dependency `package.json` declares is
    locked at the root in a version inside its range, and no package's requirement is broken
    that the file does not break already at the merge's own commit. Composer: the content-hash
    is the merged `composer.json`'s and every requirement is met. `None` when the manifest is
    missing or unreadable."""
    if not manifest:
        return None
    try:
        lock, project = json.loads(text), json.loads(manifest)
    except ValueError:
        return None
    if PurePosixPath(path).name == "composer.lock":
        if lock.get("content-hash") != composer.content_hash(manifest):
            return False
        return not composer.broken_requirements(lock, project)
    installed = lock.get("packages")
    if isinstance(installed, dict):
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            for name, wanted in (project.get(field) or {}).items():
                entry = installed.get(f"node_modules/{name}")
                if entry is None:
                    if field == "optionalDependencies":
                        continue
                    return False
                version = entry.get("version")
                if isinstance(version, str) and isinstance(wanted, str):
                    if satisfies(version, wanted) is False:
                        return False
    else:
        tree = lock.get("dependencies") or {}
        for field in ("dependencies", "devDependencies"):
            for name in project.get(field) or {}:
                if name not in tree:
                    return False
    return True


def grade(case: dict, cache: Path) -> dict:
    repo, path = case["repo"], case["path"]
    texts = {
        side: fetch(cache, repo, case[side], path) for side in ("base", "ours", "theirs", "merge")
    }
    row = {k: case[k] for k in ("repo", "merge", "path", "study")}
    if any(v is None for v in texts.values()):
        row["status"] = "unreachable"
        return row
    maintainer = texts["merge"] or ""
    if "<<<<<<<" in maintainer or ">>>>>>>" in maintainer:
        row["status"] = "maintainer committed conflict markers"
        return row
    if not maintainer:
        row["status"] = "maintainer deleted the file"
        return row
    is_composer = PurePosixPath(path).name == "composer.lock"
    manifest_name = "composer.json" if is_composer else "package.json"
    manifest = fetch(cache, repo, case["merge"], str(PurePosixPath(path).with_name(manifest_name)))
    composer_json = manifest if is_composer else None
    row["status"] = "graded"
    row["maintainer_valid"] = valid(path, maintainer, manifest)
    row["take_ours_same_set"] = _same_set(path, texts["ours"] or "", maintainer)
    row["take_theirs_same_set"] = _same_set(path, texts["theirs"] or "", maintainer)
    for mode, project in (("driver", None), ("resolve", composer_json or None)):
        outcome = lockmerge.merge(
            path,
            texts["base"] or "",
            texts["ours"] or "",
            texts["theirs"] or "",
            composer_json=project,
        )
        if isinstance(outcome, Merged):
            row[mode] = {
                "merged": True,
                "same_set": _same_set(path, outcome.text, maintainer),
                "same_json": _json_equal(outcome.text, maintainer),
                "same_bytes": outcome.text == maintainer,
                "valid": valid(path, outcome.text, manifest),
            }
        else:
            row[mode] = {
                "merged": False,
                "diverged": outcome.diverged,
                "inconsistent": outcome.inconsistent,
                "reasons": outcome.reasons[:5],
                "reason_count": len(outcome.reasons),
            }
    return row


def summarise(rows: list[dict]) -> str:
    lines = []
    status = Counter(r["status"] for r in rows)
    lines.append(f"cases: {len(rows)} ({', '.join(f'{v} {k}' for k, v in status.most_common())})")
    graded = [r for r in rows if r["status"] == "graded"]
    for kind in ("package-lock.json", "npm-shrinkwrap.json", "composer.lock"):
        group = [r for r in graded if PurePosixPath(r["path"]).name == kind]
        if not group:
            continue
        repos = len({r["repo"] for r in group})
        lines.append(f"\n{kind}: {len(group)} graded conflicts from {repos} repositories")
        for mode in ("driver", "resolve"):
            if kind != "composer.lock" and mode == "resolve":
                continue
            merged = [r for r in group if r[mode]["merged"]]
            wrong = [r for r in merged if r[mode]["same_set"] is False]
            unknown = [r for r in merged if r[mode]["same_set"] is None]
            same_json = sum(bool(r[mode]["same_json"]) for r in merged)
            judged = [r for r in merged if r[mode]["valid"] is not None]
            invalid = [r for r in judged if r[mode]["valid"] is False]
            invalid_but_maintainer_valid = [r for r in invalid if r["maintainer_valid"]]
            same_bytes = sum(bool(r[mode]["same_bytes"]) for r in merged)
            diverged = sum(1 for r in group if not r[mode]["merged"] and r[mode]["diverged"])
            inconsistent = sum(
                1 for r in group if not r[mode]["merged"] and r[mode]["inconsistent"]
            )
            other = len(group) - len(merged) - diverged - inconsistent
            lines.append(
                f"  {mode}: merged {len(merged)}/{len(group)} = {len(merged) / len(group):.3f}; "
                f"of those, package set differs from the maintainer's in {len(wrong)} "
                f"({len(wrong) / len(merged) if merged else 0:.3f}), unreadable {len(unknown)}; "
                f"identical JSON {same_json}, identical bytes {same_bytes}"
            )
            lines.append(
                f"    valid for the merged manifest: {len(judged) - len(invalid)}/{len(judged)} "
                f"judged; invalid {len(invalid)}, of which the maintainer's own file is valid "
                f"{len(invalid_but_maintainer_valid)}"
            )
            lines.append(
                f"    declined {len(group) - len(merged)}: a package changed differently on both "
                f"sides {diverged}, would break a requirement {inconsistent}, other {other}"
            )
        maintainer = [r["maintainer_valid"] for r in group if r["maintainer_valid"] is not None]
        lines.append(
            f"  calibration, the maintainer's own file valid: {sum(maintainer)}/{len(maintainer)}"
        )
        for side in ("ours", "theirs"):
            same = sum(1 for r in group if r[f"take_{side}_same_set"])
            lines.append(f"  baseline, take {side}: same package set as the maintainer {same}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()
    found = cases()
    print(f"{len(found)} lock-file conflicts", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda c: grade(c, args.cache), found))
    with (HERE / "cases.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    summary = summarise(rows)
    (HERE / "summary.txt").write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
