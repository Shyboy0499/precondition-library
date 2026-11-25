"""`composer.lock`.

`packages` and `packages-dev` are lists of resolved packages; each is merged as a map from the
package's name to its record, and each record merges whole. Everything else merges key by key.

`content-hash` is Composer's fingerprint of `composer.json` (`Locker::getContentHash`). When only
one side changed `composer.json`, that side's hash is the merged one. When both did, the hash
can only be recomputed from the merged `composer.json`; lockmerge does that when it is given one
(`lockmerge resolve` reads it from the working tree) and declines otherwise.

After merging, every package's requirements on other packages must still be met by the merged
set, and, given the merged `composer.json`, so must the project's own. A merge that breaks a
requirement neither side broke is refused.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from lockmerge._composer_constraint import satisfies
from lockmerge._merge import MISSING, Divergence, Path, merge_tree, merge_value
from lockmerge._result import Declined, Merged, Outcome

FILENAMES = ("composer.lock",)
SECTIONS = ("packages", "packages-dev")
_PLATFORM = re.compile(r"^(php(-64bit|-ipv6|-zts|-debug)?|hhvm|ext-.+|lib-.+|composer(-.+)?)$")

_RELEVANT = (
    "name",
    "version",
    "require",
    "require-dev",
    "conflict",
    "replace",
    "provide",
    "minimum-stability",
    "prefer-stable",
    "repositories",
    "extra",
)


def _php_value(value: Any) -> Any:
    """What `json_decode($text, true)` then `json_encode` round-trips a value to: an empty
    object becomes `[]`, and an object keyed `"0".."n-1"` becomes a list."""
    if isinstance(value, dict):
        if not value or list(value) == [str(i) for i in range(len(value))]:
            return [_php_value(v) for v in value.values()]
        return {k: _php_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_php_value(v) for v in value]
    return value


def content_hash(composer_json: str) -> str:
    """Composer 2's `Locker::getContentHash`, byte for byte: the relevant keys of
    `composer.json` (and `config.platform`), sorted, `json_encode`d with no flags, MD5."""
    content = json.loads(composer_json)
    relevant: dict[str, Any] = {k: content[k] for k in _RELEVANT if k in content}
    platform = (
        (content.get("config") or {}).get("platform")
        if isinstance(content.get("config"), dict)
        else None
    )
    if platform is not None:
        relevant["config"] = {"platform": platform}
    ordered = {k: relevant[k] for k in sorted(relevant)}
    encoded = json.dumps(_php_value(ordered), separators=(",", ":"), ensure_ascii=True)
    return hashlib.md5(encoded.replace("/", "\\/").encode()).hexdigest()


def _by_name(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    out: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict) or "name" not in item:
            raise ValueError("a package without a name")
        out[str(item["name"])] = item
    return out


def _reference(package: dict[str, Any]) -> tuple[Any, Any]:
    return (package.get("source") or {}).get("reference"), (package.get("dist") or {}).get(
        "reference"
    )


def _reconcile(path: Path, base: Any, ours: Any, theirs: Any) -> Any:
    """One package version recorded two ways (a field a newer Composer writes, a reordered
    key): the same version from the same commit merges, ours first."""
    if len(path) != 2 or path[0] not in SECTIONS:
        return MISSING
    if not isinstance(ours, dict) or not isinstance(theirs, dict):
        return MISSING
    same = ours.get("version") == theirs.get("version") and _reference(ours) == _reference(theirs)
    if not same or ours.get("require") != theirs.get("require"):
        return MISSING
    return {**ours, **{k: v for k, v in theirs.items() if k not in ours}}


def _atomic(path: Path) -> bool:
    return len(path) == 2 and path[0] in SECTIONS or path in (("content-hash",), ("_readme",))


def _installed(lock: dict[str, Any], project: dict[str, Any] | None) -> dict[str, str]:
    """Every name the lock installs, with its version, and every name a package (or the project
    itself) replaces or provides, with `""`: Composer accepts a virtual package whatever the
    requirement, so it is not range-checked."""
    found: dict[str, str] = {}
    virtual: set[str] = set()
    for section in SECTIONS:
        for package in lock.get(section) or []:
            found[package["name"].lower()] = str(package.get("version", ""))
            for kind in ("replace", "provide"):
                virtual.update(name.lower() for name in package.get(kind) or {})
    for kind in ("replace", "provide"):
        virtual.update(name.lower() for name in (project or {}).get(kind) or {})
    for name in virtual:
        found[name] = ""
    return found


def _within(version: str, constraint: str) -> bool:
    return satisfies(version, constraint) is not False


def broken_requirements(lock: dict[str, Any], project: dict[str, Any] | None = None) -> set[str]:
    installed = _installed(lock, project)
    broken: set[str] = set()

    def check(owner: str, requires: dict[str, Any]) -> None:
        for name, constraint in requires.items():
            if _PLATFORM.match(name.lower()):
                continue
            version = installed.get(name.lower())
            if version is None:
                broken.add(f"{owner} -> {name} {constraint} (missing)")
            elif version and isinstance(constraint, str) and not _within(version, constraint):
                broken.add(f"{owner} -> {name} {constraint} (found {version})")

    for section in SECTIONS:
        for package in lock.get(section) or []:
            check(package["name"], package.get("require") or {})
    if project is not None:
        check("composer.json", project.get("require") or {})
        if lock.get("packages-dev") is not None:
            check("composer.json (dev)", project.get("require-dev") or {})
    return broken


def _describe(divergence: Divergence) -> str:
    def version(value: Any) -> str:
        if value is MISSING:
            return "absent"
        if isinstance(value, dict) and "version" in value:
            return str(value["version"])
        return "changed"

    if len(divergence.path) == 2 and divergence.path[0] in SECTIONS:
        return (
            f"{divergence.path[1]}: base {version(divergence.base)}, ours "
            f"{version(divergence.ours)}, theirs {version(divergence.theirs)}"
        )
    return f"{'/'.join(divergence.path)} was changed differently on both sides"


def dump(lock: dict[str, Any], like: str) -> str:
    """As Composer writes it: four-space indent, slashes and Unicode unescaped, a newline."""
    text = json.dumps(lock, indent=4, ensure_ascii=False)
    return text + "\n" if like.endswith("\n") or not like else text


def merge(base: str, ours: str, theirs: str, *, composer_json: str | None = None) -> Outcome:
    try:
        b, o, t = (json.loads(text) if text.strip() else {} for text in (base, ours, theirs))
        project = json.loads(composer_json) if composer_json else None
    except json.JSONDecodeError as error:
        return Declined([f"not JSON: {error.msg} (line {error.lineno})"])
    if not all(isinstance(x, dict) for x in (b, o, t)):
        return Declined(["not a lock file: the top level is not an object"])
    try:
        keyed = [
            {k: (_by_name(v) if k in SECTIONS else v) for k, v in x.items()} for x in (b, o, t)
        ]
    except ValueError as error:
        return Declined([str(error)])
    divergences: list[Divergence] = []
    merged = merge_tree(*keyed, atomic=_atomic, divergences=divergences, reconcile=_reconcile)
    hash_diverged = [d for d in divergences if d.path == ("content-hash",)]
    divergences = [d for d in divergences if d.path != ("content-hash",)]
    if divergences:
        return Declined([_describe(d) for d in divergences], diverged=True)
    if hash_diverged:
        if project is None:
            return Declined(
                [
                    "composer.json changed on both sides, so content-hash must be recomputed "
                    "from the merged composer.json: merge it, then run `lockmerge resolve`"
                ]
            )
        merged["content-hash"] = content_hash(composer_json or "")
    elif project is not None:
        expected = content_hash(composer_json or "")
        hashed, _ = merge_value(b.get("content-hash"), o.get("content-hash"), t.get("content-hash"))
        if hashed != expected:
            merged["content-hash"] = expected
    for section in SECTIONS:
        if isinstance(merged.get(section), dict):
            merged[section] = list(merged[section].values())
    new = (
        broken_requirements(merged, project)
        - broken_requirements(o, project)
        - broken_requirements(t, project)
    )
    if new:
        return Declined(
            [f"the merge would break a requirement: {item}" for item in sorted(new)],
            inconsistent=True,
        )
    return Merged(dump(merged, ours))
