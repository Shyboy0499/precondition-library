"""Three-way merge of JSON-shaped lock files, entry by entry.

The rule is the one studies 3-5 validated on real conflicts (`results/lock-oracle-2026-11-02`,
`results/divergence-gate-2026-11-08`): take what both sides kept, each side's additions and
removals, and **refuse when one entry was changed differently on both sides**. A refused entry
is a `Divergence`; the caller decides what to do with it (lockmerge declines the whole file).

An entry is merged *atomically*: a resolved package's record (version, integrity, its own
dependencies) is taken whole from one side or the other, never stitched from both, since a
record stitched from two resolutions describes neither.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class _Missing:
    """An absent key, distinct from a key whose value is `null`."""

    def __repr__(self) -> str:
        return "<missing>"


MISSING: Any = _Missing()

Path = tuple[str, ...]


@dataclass(frozen=True)
class Divergence:
    """One entry both sides changed, differently."""

    path: Path
    base: Any
    ours: Any
    theirs: Any


def merge_value(base: Any, ours: Any, theirs: Any) -> tuple[Any, bool]:
    """The classic three-way rule on one value. Returns `(merged, diverged)`."""
    if ours == theirs:
        return ours, False
    if ours == base:
        return theirs, False
    if theirs == base:
        return ours, False
    return ours, True


def _ordered_keys(
    ours: dict[str, Any], theirs: dict[str, Any], sort_key: Callable[[str], Any]
) -> list[str]:
    """Ours' keys in ours' order, with each key only theirs has placed between the keys it sits
    between in theirs. Where that leaves a choice (keys only ours has fall in the same gap),
    `sort_key` decides, so two sides sorted by the package manager stay sorted."""
    keys_ours, keys_theirs = [sort_key(k) for k in ours], [sort_key(k) for k in theirs]
    if keys_ours == sorted(keys_ours) and keys_theirs == sorted(keys_theirs):
        return sorted({**ours, **theirs}, key=sort_key)
    order = list(ours)
    seen = set(order)
    theirs_keys = list(theirs)
    for i, key in enumerate(theirs_keys):
        if key in seen:
            continue
        before = next((k for k in reversed(theirs_keys[:i]) if k in seen), None)
        after = next((k for k in theirs_keys[i + 1 :] if k in seen), None)
        low = order.index(before) + 1 if before is not None else 0
        high = order.index(after) if after is not None else len(order)
        at = low
        while at < high and sort_key(order[at]) <= sort_key(key):
            at += 1
        order.insert(at, key)
        seen.add(key)
    return order


def _identity(key: str) -> str:
    return key


Reconcile = Callable[[Path, Any, Any, Any], Any]
"""Given a diverged atomic value, return one value both sides' changes agree on, or `MISSING`
when there is none. lockmerge uses it for one package version recorded two ways."""


def _never(path: Path, base: Any, ours: Any, theirs: Any) -> Any:
    return MISSING


def merge_tree(
    base: Any,
    ours: Any,
    theirs: Any,
    *,
    atomic: Callable[[Path], bool],
    path: Path = (),
    divergences: list[Divergence],
    sort_key: Callable[[str], Any] = _identity,
    reconcile: Reconcile = _never,
    reconciled: list[Path] | None = None,
) -> Any:
    """Merge three JSON values. Objects merge key by key, recursively, except at paths `atomic`
    names, which merge as one value. Anything else merges as one value. Returns `MISSING` when
    the merged result has no such key. A diverged atomic value goes to `reconcile` before it
    counts as a divergence; each one reconciled is appended to `reconciled`."""
    objects = all(isinstance(v, dict) or v is MISSING for v in (base, ours, theirs))
    present = [v for v in (ours, theirs) if v is not MISSING]
    if atomic(path) or not objects or not present:
        merged, diverged = merge_value(base, ours, theirs)
        if diverged:
            agreed = reconcile(path, base, ours, theirs)
            if agreed is not MISSING:
                if reconciled is not None:
                    reconciled.append(path)
                return agreed
            divergences.append(Divergence(path, base, ours, theirs))
        return merged
    if ours is MISSING or theirs is MISSING:
        # One side deleted the whole object. That is a merge only if the other left it alone.
        merged, diverged = merge_value(base, ours, theirs)
        if diverged:
            divergences.append(Divergence(path, base, ours, theirs))
        return merged
    b = base if isinstance(base, dict) else {}
    result: dict[str, Any] = {}
    for key in _ordered_keys(ours, theirs, sort_key):
        value = merge_tree(
            b.get(key, MISSING),
            ours.get(key, MISSING),
            theirs.get(key, MISSING),
            atomic=atomic,
            path=(*path, key),
            divergences=divergences,
            sort_key=sort_key,
            reconcile=reconcile,
            reconciled=reconciled,
        )
        if value is not MISSING:
            result[key] = value
    return result
