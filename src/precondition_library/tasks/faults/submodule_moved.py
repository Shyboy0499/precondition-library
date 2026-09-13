"""Fault: a submodule's recorded commit no longer matches what upstream expects.

Submodules raise the state-dependence sharply — the recovery differs depending
on whether the submodule directory is initialised, dirty, or absent entirely —
and they are a classic source of fork desynchronisation in practice.
"""

from __future__ import annotations

from ..spec import FaultSpec, GroundTruth


class SubmoduleMovedFault(FaultSpec):
    name = "submodule_moved"
    description = "A tracked submodule's pinned commit drifted from upstream's"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        return (
            "The submodule in this fork is out of step with what upstream pins. "
            "Bring it back into line."
        )

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1")


SPEC = SubmoduleMovedFault()
