"""Which lock-file action reproduces what the maintainer committed (#306).

The real-merge pilot found that no maintainer's merged lock file is either of the lock-file
intent's two line unions, and that 27 of its 30 conflicts also conflict outside the lock file.
So the question is put the way a maintainer meets it. Given the maintainer's merge of
everything else, the merged manifests included, which action on the lock file gives the lock
file they committed?

**The actions.**

* `take_local` / `take_upstream`: one side's lock file, as it is.
* `three_way`: the merge git would make if it merged lock files package by package rather than
  line by line -- what both sides kept, plus each side's additions, less each side's removals:
  `(B ∩ L ∩ U) ∪ (L − B) ∪ (U − B)` over `(package, version)` pairs. Computed exactly, with
  no tool and so no registry drift.
* `three_way_unified`: the same, then where both sides moved one package to different versions
  the tool would accept only one of, the higher is kept -- what cargo and yarn do within a
  semver-compatible range, and poetry for a name.
* `reconcile_local` / `reconcile_upstream`: one side's lock file, then the ecosystem's own
  tool brings it in line with the merged manifests, changing as little as it can:
  `cargo update --workspace`, `poetry lock` (which keeps what is locked), or
  `yarn install` (yarn 1 has no lock-only mode).
* `regenerate`: no lock file, and the tool resolves from scratch. Today's registry is not the
  registry of the merge's date, so this is expected to differ from an old merge. It is reported,
  not excluded.

**The comparison is semantic.** Each lock file is read into its set of resolved
`(package, version)` pairs (`packages`). Two lock files agree when their sets do, whatever their
formatting, ordering, checksums or format version. A tool from today writes a different format
than one from years ago, and that must not count as a different resolution.

Tools run harness-side, on a copy of the merge's tree, with registry access through the
operator's proxy; nothing here runs model-authored code.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

ACTIONS = (
    "take_local",
    "take_upstream",
    "three_way",
    "three_way_unified",
    "reconcile_local",
    "reconcile_upstream",
    "regenerate",
)

TOOL_TIMEOUT = 900.0
"""Seconds one tool run may take; `yarn install` downloads every package."""

Package = tuple[str, str]


# --- reading a lock file -----------------------------------------------------------------


def _toml_packages(text: str) -> set[Package]:
    data = tomllib.loads(text)
    return {(str(p["name"]), str(p["version"])) for p in data.get("package", [])}


_YARN_KEY = re.compile(r'^("?)(?P<specs>[^\s].*?)\1:\s*$')
_YARN_VERSION = re.compile(r'^\s+version:?\s+"?(?P<version>[^"\s]+)"?\s*$')


def _yarn_name(spec: str) -> str:
    """`@scope/name@^1.0` -> `@scope/name`; `name@npm:other@1` -> `name`."""
    spec = spec.strip().strip('"')
    at = spec.find("@", 1)
    return spec if at == -1 else spec[:at]


def _yarn_packages(text: str) -> set[Package]:
    """yarn 1's format: a key line naming the specs, then an indented `version "x"`."""
    found: set[Package] = set()
    names: list[str] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            key = _YARN_KEY.match(line)
            names = [_yarn_name(s) for s in key.group("specs").split(",")] if key else []
            continue
        version = _YARN_VERSION.match(line)
        if version and names:
            found.update((name, version.group("version")) for name in names)
            names = []
    return found


READERS = {
    "Cargo.lock": _toml_packages,
    "poetry.lock": _toml_packages,
    "yarn.lock": _yarn_packages,
}
"""The lock files this module can read, by final path component."""


def packages(path: str, text: str) -> set[Package] | None:
    """The resolved `(package, version)` pairs in a lock file, or None if it cannot be read."""
    reader = READERS.get(path.rsplit("/", 1)[-1])
    if reader is None:
        return None
    try:
        return reader(text)
    except (tomllib.TOMLDecodeError, KeyError, TypeError):
        return None


# --- running an ecosystem's tool -----------------------------------------------------------


def _tool(path: str, *, regenerate: bool) -> list[str]:
    name = path.rsplit("/", 1)[-1]
    if name == "Cargo.lock":
        return ["cargo", "generate-lockfile"] if regenerate else ["cargo", "update", "--workspace"]
    if name == "poetry.lock":
        return ["poetry", "lock", "--no-interaction"] + (["--regenerate"] if regenerate else [])
    if name == "yarn.lock":
        return [
            "yarn",
            "install",
            "--ignore-scripts",
            "--ignore-engines",
            "--ignore-platform",
            "--ignore-optional",
            "--non-interactive",
            "--network-timeout",
            "120000",
        ]
    raise ValueError(f"no tool for {path}")


def _environment(cache: Path) -> dict[str, str]:
    """The operator's environment (proxy and CA settings), with the tools' caches shared and
    a repository's own toolchain pin overridden, so no run installs an old toolchain."""
    return {
        **os.environ,
        "RUSTUP_TOOLCHAIN": "stable",
        "YARN_CACHE_FOLDER": str(cache / "yarn"),
        "POETRY_CACHE_DIR": str(cache / "poetry"),
        "POETRY_VIRTUALENVS_CREATE": "false",
        "CI": "true",
    }


class ActionResult(BaseModel):
    action: str
    reproduces: bool
    """The action's lock file resolves exactly the maintainer's `(package, version)` set."""
    reproduces_but_new: bool = False
    """The same package names as the maintainer's, and the same version of every package that
    either side or the base already had. Only a package new to the merge may differ: a tool run
    today resolves it against today's registry, not the one of the merge's date."""
    jaccard: float | None
    """|A ∩ M| / |A ∪ M| over those sets; None when the action produced no readable file."""
    error: str = ""


def _compare(produced: set[Package] | None, merged: set[Package]) -> tuple[bool, float | None]:
    if produced is None:
        return False, None
    union = produced | merged
    return produced == merged, (len(produced & merged) / len(union)) if union else 1.0


def three_way(base: set[Package], local: set[Package], upstream: set[Package]) -> set[Package]:
    """Both sides' changes to the base, package by package: kept by both, or added by either."""
    return (base & local & upstream) | (local - base) | (upstream - base)


def _release(version: str) -> tuple[int, ...]:
    """A version's leading numbers, for ordering: `0.2.161` -> (0, 2, 161)."""
    numbers = re.findall(r"\d+", version.split("+", 1)[0].split("-", 1)[0])
    return tuple(int(n) for n in numbers[:4])


def _compatible(path: str, version: str) -> tuple[int, ...]:
    """The range one version of a package must share with another to be unified."""
    if path.rsplit("/", 1)[-1] == "poetry.lock":
        return ()
    release = _release(version) + (0, 0)
    return release[:2] if release[0] == 0 else release[:1]


def unify(path: str, resolved: set[Package]) -> set[Package]:
    """Within each package's compatible range, only the highest version."""
    best: dict[tuple[str, tuple[int, ...]], str] = {}
    for name, version in resolved:
        key = (name, _compatible(path, version))
        if key not in best or _release(version) > _release(best[key]):
            best[key] = version
    return {(name, version) for (name, _), version in best.items()}


def same_but_new(produced: set[Package], merged: set[Package], before: set[str]) -> bool:
    """Same names, and the same versions of every package named in `before`."""
    names = {name for name, _ in produced}
    if names != {name for name, _ in merged}:
        return False
    return {p for p in produced if p[0] in before} == {p for p in merged if p[0] in before}


def _show(repo: Path, commit: str, path: str) -> str | None:
    shown = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    return shown.stdout if shown.returncode == 0 else None


def _checkout(repo: Path, commit: str, into: Path) -> None:
    """The merge's whole tree, without its history: what the maintainer left on disk."""
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(into)], input=archive.stdout, check=True)


def actions_on(
    repo: Path, *, merge: str, first: str, second: str, base: str, path: str, cache: Path
) -> list[ActionResult]:
    """Every action on one conflicted lock file, each compared with the maintainer's."""
    merged_text = _show(repo, merge, path)
    merged = packages(path, merged_text) if merged_text is not None else None
    if merged is None:
        return [
            ActionResult(action=a, reproduces=False, jaccard=None, error="merge's file unread")
            for a in ACTIONS
        ]
    sides = {"local": _show(repo, first, path), "upstream": _show(repo, second, path)}
    read = {side: packages(path, t) if t is not None else None for side, t in sides.items()}
    base_text = _show(repo, base, path)
    base_set = (packages(path, base_text) if base_text is not None else None) or set()
    before = {n for n, _ in base_set | (read["local"] or set()) | (read["upstream"] or set())}
    results: list[ActionResult] = []
    for side in ("local", "upstream"):
        same, jaccard = _compare(read[side], merged)
        results.append(
            ActionResult(
                action=f"take_{side}", reproduces=same, reproduces_but_new=same, jaccard=jaccard
            )
        )
    if read["local"] is not None and read["upstream"] is not None:
        combined = three_way(base_set, read["local"], read["upstream"])
        for action, candidate in (
            ("three_way", combined),
            ("three_way_unified", unify(path, combined)),
        ):
            same, jaccard = _compare(candidate, merged)
            results.append(
                ActionResult(
                    action=action, reproduces=same, reproduces_but_new=same, jaccard=jaccard
                )
            )
    else:
        for action in ("three_way", "three_way_unified"):
            results.append(
                ActionResult(
                    action=action, reproduces=False, jaccard=None, error="a side's file unread"
                )
            )
    for action, start in (
        ("reconcile_local", sides["local"]),
        ("reconcile_upstream", sides["upstream"]),
        ("regenerate", None),
    ):
        results.append(_run(repo, merge, path, start, merged, before, action, cache))
    return results


def _run(
    repo: Path,
    merge: str,
    path: str,
    start: str | None,
    merged: set[Package],
    before: set[str],
    action: str,
    cache: Path,
) -> ActionResult:
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as scratch:
        tree = Path(scratch) / "tree"
        tree.mkdir()
        _checkout(repo, merge, tree)
        lock = tree / path
        if start is None:
            lock.unlink(missing_ok=True)
        else:
            lock.write_text(start, encoding="utf-8", errors="surrogateescape")
        try:
            ran = subprocess.run(
                _tool(path, regenerate=start is None),
                cwd=lock.parent,
                env=_environment(cache),
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(action=action, reproduces=False, jaccard=None, error="timeout")
        if ran.returncode != 0 or not lock.is_file():
            tail = (ran.stderr or ran.stdout).strip().splitlines()[-1:] or [""]
            return ActionResult(
                action=action,
                reproduces=False,
                jaccard=None,
                error=f"exit {ran.returncode}: {tail[0][:200]}",
            )
        produced = packages(path, lock.read_text(encoding="utf-8"))
        same, jaccard = _compare(produced, merged)
        return ActionResult(
            action=action,
            reproduces=same,
            reproduces_but_new=produced is not None and same_but_new(produced, merged, before),
            jaccard=jaccard,
        )


def summarise(
    per_file: Sequence[Sequence[ActionResult]], *, but_new: bool = False
) -> dict[str, bool]:
    """Which actions reproduce every one of a case's lock files (`but_new`: drift-tolerant)."""
    return {
        action: all(
            (r.reproduces_but_new if but_new else r.reproduces)
            for results in per_file
            for r in results
            if r.action == action
        )
        for action in ACTIONS
    }


def clear(cache: Path) -> None:
    shutil.rmtree(cache, ignore_errors=True)


# --- over a stage's cases --------------------------------------------------------------------


class LockFileActions(BaseModel):
    path: str
    results: list[ActionResult]


class CaseActions(BaseModel):
    index: int
    repo: str
    merge: str
    only_locks_conflicted: bool
    files: list[LockFileActions]
    reproduces: dict[str, bool]
    """Per action: whether it reproduces every one of the case's conflicted lock files."""
    reproduces_but_new: dict[str, bool]
    """The same, allowing a package new to the merge to resolve to a later version."""


def run_on_stage(stage: Path, out: Path, work: Path) -> list[CaseActions]:
    """Every action on every conflicted lock file of a stage's conflicted cases."""
    from .real_merges import Manifest, fetch_real_host, host, is_lock

    if out.exists():
        raise ValueError(f"{out} already exists; the run writes a fresh file")
    manifest = Manifest.model_validate_json((stage / "manifest.json").read_text("utf-8"))
    tips = {r.repo: r.tip for r in manifest.repositories}
    work.mkdir(parents=True, exist_ok=True)
    found: list[CaseActions] = []
    for case in manifest.cases:
        if case.kind != "positive":
            continue
        repo = fetch_real_host(host(case.repo, tips[case.repo]))
        locks = [p for p in case.conflicted if is_lock(p) and p.rsplit("/", 1)[-1] in READERS]
        files = [
            LockFileActions(
                path=path,
                results=actions_on(
                    repo,
                    merge=case.merge,
                    first=case.first,
                    second=case.second,
                    base=case.base,
                    path=path,
                    cache=work,
                ),
            )
            for path in locks
        ]
        found.append(
            CaseActions(
                index=case.index,
                repo=case.repo,
                merge=case.merge,
                only_locks_conflicted=len(locks) == len(case.conflicted),
                files=files,
                reproduces=summarise([f.results for f in files]),
                reproduces_but_new=summarise([f.results for f in files], but_new=True),
            )
        )
        print(f"{case.index} {case.repo} {case.merge[:8]} {found[-1].reproduces}", flush=True)
    out.write_text("".join(c.model_dump_json() + "\n" for c in found), encoding="utf-8")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m precondition_library.bench.lock_actions")
    parser.add_argument("--stage", type=Path, required=True, help="a real-merge stage directory")
    parser.add_argument("--out", type=Path, required=True, help="a .jsonl file to write")
    parser.add_argument("--work", type=Path, required=True, help="scratch and tool caches")
    args = parser.parse_args(argv)
    run_on_stage(args.stage, args.out, args.work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
