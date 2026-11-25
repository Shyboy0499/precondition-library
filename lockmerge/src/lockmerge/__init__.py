"""lockmerge: merge lock files package by package, and refuse when a merge is not safe.

A git merge driver for `package-lock.json`, `npm-shrinkwrap.json` and `composer.lock`. It takes
what both sides kept, each side's additions and removals, record by record. It merges only when
no package was changed differently on both sides and the merged file still satisfies every
dependency requirement neither side broke; otherwise it hands the conflict back to git, with the
packages that diverged named, for the package manager or a person to settle.

The rule comes from this repository's registered studies of real lock-file conflicts (see
`lockmerge/README.md`, and `results/lockmerge-*/` for its measurements).
"""

from __future__ import annotations

from pathlib import PurePosixPath

from lockmerge import composer, npm
from lockmerge._result import Declined, Merged, Outcome

__all__ = ["Declined", "Merged", "Outcome", "SUPPORTED", "merge", "supported"]
__version__ = "0.1.0"

SUPPORTED = (*npm.FILENAMES, *composer.FILENAMES)


def supported(path: str) -> bool:
    return PurePosixPath(path).name in SUPPORTED


def merge(
    path: str, base: str, ours: str, theirs: str, *, composer_json: str | None = None
) -> Outcome:
    """Merge one lock file. `path` names it (only its file name is read); `base`, `ours` and
    `theirs` are its three versions' text, `""` for a side that has none. For `composer.lock`,
    `composer_json` is the merged `composer.json`, when one is available."""
    name = PurePosixPath(path).name
    if name in npm.FILENAMES:
        return npm.merge(base, ours, theirs)
    if name in composer.FILENAMES:
        return composer.merge(base, ours, theirs, composer_json=composer_json)
    return Declined([f"{name} is not a lock file lockmerge knows"])
