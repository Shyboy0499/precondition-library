"""Fault: syncing upstream produces a merge conflict inside a generated lockfile.

The most interesting fault for the mismatch metric. A conflict in a generated
file should be resolved by regenerating the lockfile with the ecosystem's own
tool, never by hand-editing conflict markers — and a program that hand-edits
markers will still *report success*, which is exactly the silent-wrong-action
failure arm 3 exists to catch. Included as much for the negative sandboxes it
supplies as for the positive ones.
"""

from __future__ import annotations

from ..spec import FaultSpec, GroundTruth


class LockfileConflictFault(FaultSpec):
    name = "lockfile_conflict"
    description = "Upstream moved dependencies, conflicting inside a generated lockfile"

    def inject(self, seed: int, sandbox) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def task_text(self, seed: int) -> str:
        return (
            "The sync hit a conflict in the lockfile. Resolve it the way this project "
            "expects, and leave dependency state consistent."
        )

    def check(self, sandbox) -> GroundTruth:
        raise NotImplementedError("implemented per plan: phase 1")


SPEC = LockfileConflictFault()
