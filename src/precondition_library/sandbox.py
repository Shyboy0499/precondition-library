"""Throwaway environments for episodes.

Every episode runs against a sandbox built here — a working clone plus a bare
"upstream" repo — and is destroyed afterwards. Phase 1 never touches a real
fork: replayed programs execute unattended, so the only safe target is a
repository that can be deleted without consequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Sandbox:
    """A disposable environment and the handles needed to inspect it."""

    root: Path
    work: Path
    """Working clone the agent operates on."""
    upstream: Path
    """Bare repo standing in for a real upstream."""

    def destroy(self) -> None:
        raise NotImplementedError("implemented per plan: phase 1")


def create(seed: int, faults: list[str]) -> Sandbox:
    """Build a sandbox with the named faults injected, deterministically.

    Determinism is required for the ablation: both arms must face byte-identical
    environments, and a re-run of the same seed must reproduce the same episode.
    """
    raise NotImplementedError("implemented per plan: phase 1")
