"""Registry of the task family.

Import order defines nothing; the registry is the single place the benchmark
asks "what faults exist". Adding a fault here extends every arm at once.
"""

from __future__ import annotations

from ..spec import FaultSpec
from .branch_renamed import SPEC as BRANCH_RENAMED
from .dirty_tree import SPEC as DIRTY_TREE
from .diverged import SPEC as DIVERGED
from .lockfile_conflict import SPEC as LOCKFILE_CONFLICT
from .submodule_moved import SPEC as SUBMODULE_MOVED

FAULTS: dict[str, FaultSpec] = {
    spec.name: spec
    for spec in (
        DIRTY_TREE,
        DIVERGED,
        BRANCH_RENAMED,
        SUBMODULE_MOVED,
        LOCKFILE_CONFLICT,
    )
}

ALL: list[str] = sorted(FAULTS)

__all__ = ["ALL", "FAULTS"]
