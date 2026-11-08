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

import json
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
    """Cargo.lock, poetry.lock and uv.lock: one `[[package]]` table per resolved package. A uv
    workspace member with a dynamic version has none, and is read with an empty one."""
    data = tomllib.loads(text)
    return {(str(p["name"]), str(p.get("version", ""))) for p in data.get("package", [])}


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
        if version and names and names != ["__metadata"]:
            found.update((name, version.group("version")) for name in names)
            names = []
    return found


def _npm_packages(text: str) -> set[Package]:
    """package-lock.json and npm-shrinkwrap.json. Format 2 and 3 key every installed copy by its
    path (`node_modules/a/node_modules/b`); format 1 nests `dependencies`. A workspace's own
    directories and links are the project, not a resolution, and are left out."""
    data = json.loads(text)
    found: set[Package] = set()
    if isinstance(data.get("packages"), dict):
        for key, entry in data["packages"].items():
            if "node_modules/" not in key or entry.get("link") or "version" not in entry:
                continue
            found.add((key.rsplit("node_modules/", 1)[1], str(entry["version"])))
        return found

    def walk(dependencies: dict[str, dict]) -> None:
        for name, entry in dependencies.items():
            if "version" in entry:
                found.add((name, str(entry["version"])))
            walk(entry.get("dependencies", {}))

    walk(data["dependencies"])
    return found


_PNPM_KEY = re.compile(r"""^  (['"]?)(?P<key>[^\s'"].*?)\1:\s*$""")


def _pnpm_key(key: str) -> Package:
    """`/a/1.0.0_b@2` (format 5), `/@s/a@1.0.0(b@2)` (6) and `a@1.0.0` (9) -> `(a, 1.0.0)`."""
    key = key.lstrip("/").split("(", 1)[0]
    name, _, last = key.rpartition("/")
    if name and last[:1].isdigit():
        return name, last.split("_", 1)[0]
    at = key.rfind("@")
    return key[:at], key[at + 1 :]


def _pnpm_packages(text: str) -> set[Package]:
    """pnpm-lock.yaml's `packages:` block, one key per resolved package, read line by line so a
    snapshot section or an importer never counts."""
    found: set[Package] = set()
    inside = False
    for line in text.splitlines():
        if line and not line[0].isspace():
            inside = line.rstrip() == "packages:"
            continue
        key = _PNPM_KEY.match(line) if inside else None
        if key:
            found.add(_pnpm_key(key.group("key")))
    if "packages:" not in text.splitlines():
        raise KeyError("packages")
    return found


def _pipenv_packages(text: str) -> set[Package]:
    """Pipfile.lock: `default` and `develop`, each a name with a pinned `==version`. A VCS or
    path requirement pins no version and is read with its reference instead."""
    data = json.loads(text)
    found: set[Package] = set()
    for section in ("default", "develop"):
        for name, entry in data.get(section, {}).items():
            pinned = entry.get("version") or entry.get("ref") or entry.get("path") or ""
            found.add((name.lower(), str(pinned).removeprefix("==")))
    return found


def _composer_packages(text: str) -> set[Package]:
    data = json.loads(text)
    return {
        (str(p["name"]), str(p["version"]))
        for section in ("packages", "packages-dev")
        for p in data.get(section) or []
    }


_GEM_SPEC = re.compile(r"^    (?P<name>[^\s(]+) \((?P<version>[^)]+)\)\s*$")


def _gem_packages(text: str) -> set[Package]:
    """Gemfile.lock: every `specs:` entry at four spaces, from GEM, GIT and PATH sections. Six
    spaces is a gem's own requirement, not a resolution. A platform gem keeps its platform in
    its version (`1.15.4-x86_64-linux`), so each platform's copy is its own pair."""
    found = {
        (m.group("name"), m.group("version")) for m in map(_GEM_SPEC.match, text.splitlines()) if m
    }
    return found


READERS = {
    "Cargo.lock": _toml_packages,
    "poetry.lock": _toml_packages,
    "uv.lock": _toml_packages,
    "yarn.lock": _yarn_packages,
    "package-lock.json": _npm_packages,
    "npm-shrinkwrap.json": _npm_packages,
    "pnpm-lock.yaml": _pnpm_packages,
    "Pipfile.lock": _pipenv_packages,
    "composer.lock": _composer_packages,
    "Gemfile.lock": _gem_packages,
}
"""The lock files this module can read, by final path component."""


_CONFLICT = re.compile(r"^(<{7}|>{7})( |$)", re.MULTILINE)
"""A file committed with conflict markers in it resolves nothing; reading part of it would."""


def packages(path: str, text: str) -> set[Package] | None:
    """The resolved `(package, version)` pairs in a lock file, or None if it cannot be read."""
    reader = READERS.get(path.rsplit("/", 1)[-1])
    if reader is None or _CONFLICT.search(text):
        return None
    try:
        return reader(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
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


ONE_VERSION = ("poetry.lock", "uv.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock")
"""Ecosystems whose resolver installs one version of a package, so unifying keeps one."""


def _compatible(path: str, version: str) -> tuple[int | str, ...]:
    """The range one version of a package must share with another to be unified: a semver
    caret range for cargo and npm's three lock files, which may hold several incompatible
    versions of one package; everything, for one-version ecosystems -- save a Ruby platform gem,
    whose copies for different platforms coexist."""
    name = path.rsplit("/", 1)[-1]
    if name == "Gemfile.lock":
        platform = re.match(r"^[\d.]+(?:\.[a-z]+\d*)?-(?P<platform>.+)$", version)
        return (platform.group("platform"),) if platform else ()
    if name in ONE_VERSION:
        return ()
    release = _release(version) + (0, 0)
    return release[:2] if release[0] == 0 else release[:1]


_FINAL = re.compile(r"v?\d+(\.\d+)*")


def _order(version: str) -> tuple[tuple[int, ...], bool, str]:
    """How versions rank within a compatible range: by release numbers, then a final release
    above a pre-release with the same numbers (`1.0.0` above `1.0.0-beta.1`), then by text.

    The last two only break ties between versions whose release numbers are equal. Before
    2026-11-02 such ties were broken by set order, which can differ between processes. On
    studies 3 and 4 that changed no verdict (`results/ecosystem-unify-2026-11-02/README.md`).
    """
    return _release(version), bool(_FINAL.fullmatch(version.split("+", 1)[0])), version


def unify(path: str, resolved: set[Package]) -> set[Package]:
    """Within each package's compatible range, only the highest version (`_order`)."""
    best: dict[tuple[str, tuple[int | str, ...]], str] = {}
    for name, version in resolved:
        key = (name, _compatible(path, version))
        if key not in best or _order(version) > _order(best[key]):
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
    """The merge's whole tree, without its history: what the maintainer left on disk.

    Every blob is written as committed. `git archive` is not used: it applies the repository's
    own `export-ignore` and `export-subst` attributes, which leave out files such as a
    `composer.json` that a project keeps out of its release archives, or rewrite them.
    Submodules are left empty, as a fresh clone leaves them."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree", commit],
        capture_output=True,
        check=True,
    ).stdout
    entries: list[tuple[bytes, str, str]] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, sha = meta.split(b" ")
        if kind == b"blob":
            entries.append((mode, sha.decode(), os.fsdecode(raw_path)))
    if not entries:
        return
    batch = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch"],
        input="".join(f"{blob}\n" for _, blob, _ in entries).encode(),
        capture_output=True,
        check=True,
    ).stdout
    at = 0
    for kind_mode, _, path in entries:
        header_end = batch.index(b"\n", at)
        size = int(batch[at:header_end].split(b" ")[2])
        content = batch[header_end + 1 : header_end + 1 + size]
        at = header_end + 1 + size + 1
        target = into / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind_mode == b"120000":
            target.symlink_to(os.fsdecode(content))
        else:
            target.write_bytes(content)
            if kind_mode == b"100755":
                target.chmod(0o755)


COMPUTED = ("take_local", "take_upstream", "three_way", "three_way_unified")
"""The actions computed from the three sides' files alone, with no tool and no registry."""


class _Sides(BaseModel):
    merged: set[Package] | None
    texts: dict[str, str | None]
    read: dict[str, set[Package] | None]
    base: set[Package]
    before: set[str]


def _sides(repo: Path, *, merge: str, first: str, second: str, base: str, path: str) -> _Sides:
    merged_text = _show(repo, merge, path)
    texts = {"local": _show(repo, first, path), "upstream": _show(repo, second, path)}
    read = {side: packages(path, t) if t is not None else None for side, t in texts.items()}
    base_text = _show(repo, base, path)
    base_set = (packages(path, base_text) if base_text is not None else None) or set()
    return _Sides(
        merged=packages(path, merged_text) if merged_text is not None else None,
        texts=texts,
        read=read,
        base=base_set,
        before={n for n, _ in base_set | (read["local"] or set()) | (read["upstream"] or set())},
    )


def computed_actions(
    repo: Path, *, merge: str, first: str, second: str, base: str, path: str
) -> list[ActionResult]:
    """The `COMPUTED` actions on one conflicted lock file, each compared with the maintainer's."""
    sides = _sides(repo, merge=merge, first=first, second=second, base=base, path=path)
    return _computed(path, sides)


def _computed(path: str, sides: _Sides) -> list[ActionResult]:
    merged, read, base_set = sides.merged, sides.read, sides.base
    if merged is None:
        return [
            ActionResult(action=a, reproduces=False, jaccard=None, error="merge's file unread")
            for a in COMPUTED
        ]
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
    return results


def actions_on(
    repo: Path, *, merge: str, first: str, second: str, base: str, path: str, cache: Path
) -> list[ActionResult]:
    """Every action on one conflicted lock file, each compared with the maintainer's."""
    sides = _sides(repo, merge=merge, first=first, second=second, base=base, path=path)
    if sides.merged is None:
        return [
            ActionResult(action=a, reproduces=False, jaccard=None, error="merge's file unread")
            for a in ACTIONS
        ]
    results = _computed(path, sides)
    for action, start in (
        ("reconcile_local", sides.texts["local"]),
        ("reconcile_upstream", sides.texts["upstream"]),
        ("regenerate", None),
    ):
        results.append(_run(repo, merge, path, start, sides.merged, sides.before, action, cache))
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
