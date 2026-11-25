"""`package-lock.json` and `npm-shrinkwrap.json`, lockfile formats 1, 2 and 3.

Format 2 and 3 record every installed copy under `packages`, keyed by its path
(`node_modules/a/node_modules/b`); each such record is one resolution and merges whole. The root
record `""` mirrors `package.json` and merges field by field, as git merged `package.json`
itself. Format 1 (and format 2's legacy copy) nests the tree under `dependencies`; there each
top-level dependency merges whole, nested children included.

After merging, every package's required dependencies must still resolve, by npm's own lookup
(the nearest `node_modules` up the tree), to an installed version inside the required range. A
merge that breaks a requirement neither side broke is refused: that is the case where both
sides changed *different* packages that depend on each other.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lockmerge._merge import MISSING, Divergence, Path, merge_tree
from lockmerge._result import Declined, Merged, Outcome
from lockmerge._semver import satisfies

FILENAMES = ("package-lock.json", "npm-shrinkwrap.json")

_INDENT = re.compile(r'^\{\s*\n([ \t]+)"', re.MULTILINE)


# The order of the characters npm's keys use under `localeCompare(_, "en")`, which npm sorts
# `packages` and `dependencies` by: punctuation, then digits, then letters, case aside.
_COLLATION = {
    c: i
    for i, c in enumerate("_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$0123456789abcdefghijklmnopqrstuvwxyz")
}


def _collation_key(key: str) -> tuple[tuple[int, ...], str]:
    return tuple(_COLLATION.get(c, 1000 + ord(c)) for c in key.lower()), key


def _atomic(path: Path) -> bool:
    if len(path) == 2 and path[0] == "packages":
        return path[1] != ""
    if len(path) == 2 and path[0] == "dependencies":
        return True
    return False


# Flags npm derives from where a package sits in the tree. `npm ci --omit=dev` skips a package
# marked `dev`, so a flag is kept only when both sides set it: an unsure merge installs more.
_FLAGS = ("dev", "optional", "devOptional", "peer")
_TARBALL = re.compile(r"^https?://[^#]+/(?P<file>[^/#]+\.tgz)$")
_DEPENDENCY_FIELDS = ("dependencies", "optionalDependencies", "peerDependencies")


def _same_resolution(ours: dict[str, Any], theirs: dict[str, Any]) -> bool:
    """Both records install the same thing: one version, from the same place (or the same
    published tarball, from two registry mirrors), with the same requirements."""
    if "version" not in ours or ours.get("version") != theirs.get("version"):
        return False
    if any(ours.get(f) != theirs.get(f) for f in (*_DEPENDENCY_FIELDS, "link", "bundled")):
        return False
    a, b = ours.get("resolved"), theirs.get("resolved")
    if a == b:
        return True
    ta, tb = _TARBALL.match(a or ""), _TARBALL.match(b or "")
    return bool(ta and tb and ta.group("file") == tb.group("file"))


def _reconcile(path: Path, base: Any, ours: Any, theirs: Any) -> Any:
    """One package version recorded two ways (flags, hashes, fields a newer npm writes): keep
    every field, ours first, flags only where both sides agree, the stronger integrity hash."""
    if len(path) != 2 or path[0] not in ("packages", "dependencies"):
        return MISSING
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return MISSING
    if not _same_resolution(ours, theirs):
        return MISSING
    merged = {**ours, **{k: v for k, v in theirs.items() if k not in ours}}
    for flag in _FLAGS:
        if ours.get(flag) and theirs.get(flag):
            merged[flag] = ours[flag]
        else:
            merged.pop(flag, None)
    integrity = [x.get("integrity") for x in (ours, theirs) if x.get("integrity")]
    strong = [i for i in integrity if str(i).startswith("sha512-")]
    if strong:
        merged["integrity"] = strong[0]
    return merged


def _parent(location: str) -> str | None:
    """The location npm searches next when resolving from `location`, or `None` at the root."""
    if location == "":
        return None
    head, sep, _ = location.rpartition("node_modules/")
    if not sep:
        return ""  # a workspace directory resolves from the root next
    return head.rstrip("/")


def _resolve(packages: dict[str, Any], location: str, name: str) -> dict[str, Any] | None:
    at: str | None = location
    while at is not None:
        candidate = f"{at}/node_modules/{name}" if at else f"node_modules/{name}"
        if candidate in packages:
            entry = packages[candidate]
            if entry.get("link") and isinstance(entry.get("resolved"), str):
                return packages.get(entry["resolved"], entry)
            return entry
        at = _parent(at)
    return None


def broken_requirements(lock: dict[str, Any]) -> set[str]:
    """`location -> name@range` for every required dependency that does not resolve to a
    version in range. Optional and peer dependencies are not required, and a range this module
    cannot read is not judged."""
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return set()
    broken: set[str] = set()
    for location, entry in packages.items():
        if not isinstance(entry, dict) or entry.get("link") or entry.get("extraneous"):
            continue
        fields = ["dependencies"]
        if "node_modules/" not in f"/{location}":
            fields.append("devDependencies")  # the project and its workspaces install these
        required = {
            name: wanted for field in fields for name, wanted in (entry.get(field) or {}).items()
        }
        for name, wanted in required.items():
            found = _resolve(packages, location, name)
            if found is None:
                broken.add(f"{location or '(root)'} -> {name}@{wanted} (missing)")
                continue
            version = found.get("version")
            if isinstance(version, str) and isinstance(wanted, str):
                if satisfies(version, wanted) is False:
                    broken.add(f"{location or '(root)'} -> {name}@{wanted} (found {version})")
    return broken


def _describe(divergence: Divergence) -> str:
    def version(value: Any) -> str:
        if value is MISSING:
            return "absent"
        if isinstance(value, dict) and "version" in value:
            return str(value["version"])
        return "changed"

    where = "/".join(divergence.path) or "(file)"
    if len(divergence.path) == 2 and divergence.path[0] in ("packages", "dependencies"):
        where = divergence.path[1].rpartition("node_modules/")[2] or divergence.path[1]
    return (
        f"{where}: base {version(divergence.base)}, ours {version(divergence.ours)}, "
        f"theirs {version(divergence.theirs)}"
    )


def dump(lock: dict[str, Any], like: str) -> str:
    """Write the lock as npm does (`JSON.stringify(lock, null, indent)` and a newline), with the
    indentation of `like`, the file it replaces."""
    found = _INDENT.search(like)
    indent = found.group(1) if found else "  "
    text = json.dumps(lock, indent=indent, ensure_ascii=False)
    return text + "\n" if like.endswith("\n") or not like else text


def merge(base: str, ours: str, theirs: str) -> Outcome:
    try:
        b, o, t = (json.loads(text) if text.strip() else {} for text in (base, ours, theirs))
    except json.JSONDecodeError as error:
        return Declined([f"not JSON: {error.msg} (line {error.lineno})"])
    if not all(isinstance(x, dict) for x in (b, o, t)):
        return Declined(["not a lock file: the top level is not an object"])
    versions = {x.get("lockfileVersion") for x in (o, t)}
    if len(versions) != 1:
        return Declined(
            [f"the two sides use different lockfile formats: {sorted(map(str, versions))}"]
        )
    divergences: list[Divergence] = []
    merged = merge_tree(
        b,
        o,
        t,
        atomic=_atomic,
        divergences=divergences,
        sort_key=_collation_key,
        reconcile=_reconcile,
    )
    if divergences:
        return Declined([_describe(d) for d in divergences], diverged=True)
    broken = broken_requirements(merged)
    # A break inside the tree that one side already had is that side's, not the merge's. A break
    # at the project's own root is never passed on: the result would fail `npm ci`.
    new = (broken - broken_requirements(o) - broken_requirements(t)) | {
        item for item in broken if item.startswith("(root) ")
    }
    if new:
        return Declined(
            [f"the merge would break a requirement: {item}" for item in sorted(new)],
            inconsistent=True,
        )
    return Merged(dump(merged, ours))
