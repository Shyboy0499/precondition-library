"""Registry of the task family.

Import order defines nothing; the registry is the single place the benchmark
asks "what faults exist". Adding a fault here extends every arm at once.
"""

from __future__ import annotations

from dataclasses import replace

from ...sandbox import Sandbox, create
from ...signatures import StateFingerprint
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


def declared_resolution_matches(fault: str, seed: int, sandbox: Sandbox) -> None:
    """Refuse a build whose observed resolution is not the one declared for `seed`.

    ADR-0005 decision 3, and the reason the axis declaration is enforceable rather
    than aspirational. A fault's seed-to-resolution map (`variant_for_seed`) is a
    claim about what `inject` will build; the injector now builds from a *draw*
    (`draw_for_seed`), and a draw that moves an axis across a decision boundary --
    a `rebase` local edit landing in a file upstream also touched, say -- would
    feed a mislabelled environment into the comparison silently. So the harness
    re-derives the resolution from the environment's own `StateFingerprint` and
    raises when the two disagree, instead of trusting the declaration.

    This is the exact function `build_sandbox` calls after injection, so a test can
    exercise it directly with a mismatched pair, and `build_sandbox` calls it for
    every single-fault build. A fault with no ambiguous intent has no resolution
    label to protect and is left alone; the fingerprint is still read for every
    measurable fault, which is the one extra observation the ADR accepts.

    The message names both resolutions and the observed discriminators, because
    "the label is wrong" is not actionable and the discriminators are the axes
    whose draw moved a predicate.
    """
    # Imported lazily: `tasks.registry` imports the fault modules, so a module-level
    # import here would be a cycle (this package's `__init__` runs first).
    from ..registry import ambiguous_intents

    intent = next((spec for spec in ambiguous_intents() if spec.fault == fault), None)
    if intent is None:
        return
    observed = StateFingerprint.observe(sandbox)
    correct = intent.correct_variant(observed)
    actual = correct.id if correct is not None else None
    declared = FAULTS[fault].variant_for_seed(seed)
    if actual != declared:
        raise ValueError(
            f"{fault}: the instance drawn at seed {seed} has resolution {actual!r} by its "
            f"observed fingerprint, but variant_for_seed declared {declared!r}; the axis "
            f"draw flipped the label, so the build is refused (ADR-0005 decision 3). "
            f"Declared instance: {FAULTS[fault].instance_for_seed(seed)!r}. Observed "
            f"discriminators: has_local_only_commits={observed.has_local_only_commits}, "
            f"local_touched_files={observed.local_touched_files}, "
            f"upstream_touched_files={observed.upstream_touched_files}, "
            f"submodule_initialised={observed.submodule_initialised}, "
            f"upstream_still_references_submodule={observed.upstream_still_references_submodule}, "
            f"submodule_pin_matches_upstream={observed.submodule_pin_matches_upstream}"
        )


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

    After injection the harness re-derives the resolution from the observed
    fingerprint and refuses a disagreement (`declared_resolution_matches`), then
    records the instance identity on the sandbox beside the injected state, so the
    label and the independence key travel on the harness object rather than in the
    clone (ADR-0005 decisions 3 and 4; issue #103).
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
        spec = FAULTS[faults[0]]
        # The label-protecting invariant first: a mislabelled build must not be
        # returned, and the recorded state/instance below are that label.
        declared_resolution_matches(faults[0], seed, sandbox)
        # The selector a checker needs, kept in the harness's own object. Recording it
        # in the clone instead is the leak issue #103 describes.
        sandbox = replace(
            sandbox,
            injected_state=spec.variant_for_seed(seed),
            instance=spec.instance_for_seed(seed),
        )
    return sandbox


__all__ = ["ALL", "FAULTS", "build_sandbox", "declared_resolution_matches"]
