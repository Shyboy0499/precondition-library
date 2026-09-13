"""Fault: a submodule's recorded commit no longer matches what upstream expects.

Three resolutions, indistinguishable from the request text:

  init    the submodule directory was never initialised in this clone.
  repin   it is initialised, upstream still tracks it, and the recorded commit drifted.
  remove  upstream no longer references the submodule at all.

The third is the one that punishes a plausible wrong answer: re-pinning a
submodule upstream has dropped *looks* like it worked (the command succeeds) while
leaving the tree in a state the checker rejects. That is exactly the silent
wrong-program fire the primary claim is about, which is why this intent is worth
having even though the first two resolutions are less interesting.
"""

from __future__ import annotations

from ...signatures import StateFingerprint
from ..intent import IntentSpec, ResolutionVariant
from ..spec import FaultSpec, GroundTruth


def _upstream_dropped_it(state: StateFingerprint) -> bool:
    return not state.upstream_still_references_submodule


def _not_initialised(state: StateFingerprint) -> bool:
    return state.upstream_still_references_submodule and not state.submodule_initialised


def _pin_drifted(state: StateFingerprint) -> bool:
    return (
        state.upstream_still_references_submodule
        and state.submodule_initialised
        and not state.submodule_pin_matches_upstream
    )


VARIANTS = [
    ResolutionVariant(
        id="remove",
        decided_by=_upstream_dropped_it,
        rationale="Upstream's tree no longer contains the submodule, so it must go.",
    ),
    ResolutionVariant(
        id="init",
        decided_by=_not_initialised,
        rationale="Upstream still tracks it but this clone never initialised it.",
    ),
    ResolutionVariant(
        id="repin",
        decided_by=_pin_drifted,
        rationale="Initialised and still tracked, but recording a commit upstream no longer pins.",
    ),
]

INTENT = IntentSpec(
    name="restore_submodule_state",
    fault="submodule_moved",
    phrasings=[
        "The submodule in this fork is out of step with upstream. Bring it back into line.",
        "Something is off with the nested repository here. Put it right.",
        "Get this repo's nested dependency consistent with upstream.",
        "One of the nested checkouts looks wrong. Resolve it.",
        "Upstream and this clone disagree about a nested repository. Reconcile them.",
        "Sort out the nested checkout so it matches what upstream expects.",
        "A nested repository in this project needs bringing into line.",
    ],
    naming_markers=["submodule"],
    variants=VARIANTS,
)


class SubmoduleMovedFault(FaultSpec):
    name = "submodule_moved"
    description = "A tracked submodule's pinned commit drifted from upstream's"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1 (issue #4)")

    def task_text(self, seed: int) -> str:
        return INTENT.task_text(seed)

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1 (issue #9)")


SPEC = SubmoduleMovedFault()
