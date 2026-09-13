"""Running episodes: the repeat structure that makes the claim testable.

Why the shape of this file is part of the argument rather than plumbing: a
claim about amortization needs repeats, and repeats need to be *comparable*.
Each fault type is therefore injected `occurrences` times with different seeds,
so that occurrence_index counts genuine recurrences of a task family rather
than repetitions of one scripted scenario. The seed varies across occurrences
and the fault type stays fixed, which is the experimental design in one line.

Each arm builds its library from empty and sees the same faults in the same
order, so the arms cannot differ by luck of scheduling.
"""

from __future__ import annotations

from pathlib import Path

from .ledger import Arm


def run_benchmark(
    *,
    arms: list[Arm],
    faults: list[str],
    occurrences: int,
    seeds: list[int],
    out: Path,
    model: str,
) -> Path:
    """Run every (arm, fault, occurrence) episode and write the ledger.

    Episodes within an arm run in occurrence order — the library must accumulate
    the way it would in use, so an arm cannot benefit from a program compiled
    against a later state. Returns the ledger path.
    """
    raise NotImplementedError("implemented per plan: phase 4")


def run_episode(arm: Arm, fault_type: str, seed: int, occurrence: int):
    """One episode: build a sandbox, let the arm act, check ground truth, record.

    Ground truth is checked for every arm with the same fault checker, so
    success means the same thing everywhere.
    """
    raise NotImplementedError("implemented per plan: phase 4")
