"""Registry of the task family.

Import order defines nothing; the registry is the single place the benchmark
asks "what faults exist". Adding a fault here extends every arm at once.
"""

from __future__ import annotations

from dataclasses import replace

from ...sandbox import Sandbox, create
from ..invariants import record_refs_at_start
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


def build_sandbox(seed: int, faults: list[str]) -> Sandbox:
    """Create a sandbox and inject `faults` into it, in the order given.

    This is where the two steps meet, and the side they meet on is the point:
    the fault registry depends on `sandbox`, never the reverse (spec §4). An
    earlier version reached the other way -- `sandbox.create` imported this
    registry inside the function to inject on the caller's behalf -- which put
    `sandbox`, every fault injector and the task registry in one import cycle.
    Keeping the call here is what makes the direction checkable rather than
    conventional.

    Validation runs before `create`, so an unknown name is refused without
    leaving a half-built sandbox behind, and injection runs *after* `create`
    returns, so a fault always mutates a fully seeded clone. Both are the
    behaviour the old in-`create` loop had; only the module that owns it moved.
    """
    unknown = sorted(set(faults) - set(FAULTS))
    if unknown:
        raise ValueError(f"unknown faults {unknown}; known: {sorted(FAULTS)}")

    sandbox = create(seed, faults)
    for name in faults:
        FAULTS[name].inject(seed, sandbox)
    # After injection, not before: injectors legitimately delete and rename upstream
    # refs, so a pre-injection snapshot would call the fault itself a violation.
    record_refs_at_start(sandbox)
    if len(faults) == 1:
        # The selector a checker needs, kept in the harness's own object. Recording it
        # in the clone instead is the leak issue #103 describes.
        sandbox = replace(sandbox, injected_state=FAULTS[faults[0]].variant_for_seed(seed))
    return sandbox


__all__ = ["ALL", "FAULTS", "build_sandbox"]
