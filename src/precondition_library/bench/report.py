"""Turning the ledger into the two figures the project stands or falls on.

Figure 1 — cost vs repeat: tokens and LLM calls per episode, grouped by
occurrence_index, one line per arm. It either shows the compiled arms pulling
away from the flat ReAct line or it does not; the crossover point is the
honest headline.

Figure 2 — mismatch rate: how often a dispatched program's preconditions
claimed applicability and the program then failed its postconditions, arm 2
against arm 3 at matched library size. This is the comparative claim.

Reported with denominators attached and confidence intervals where the counts
are small, because a mismatch rate over a handful of episodes is noise and
should look like noise.
"""

from __future__ import annotations

from pathlib import Path


def ablation_table(ledger: Path):
    """Wide table: one row per (arm, fault_type, occurrence_index).

    Columns include episodes, success rate, mismatch rate, mean tokens,
    mean LLM calls, and mean wall clock — each with its denominator.
    """
    raise NotImplementedError("implemented per plan: phase 4")


def cost_curve(ledger: Path):
    """Figure 1. Mean tokens per episode against occurrence_index, per arm."""
    raise NotImplementedError("implemented per plan: phase 4")


def mismatch_comparison(ledger: Path):
    """Figure 2. Arm 2 vs arm 3 mismatch rate, with intervals, matched on N."""
    raise NotImplementedError("implemented per plan: phase 4")


def write_report(ledger: Path, dest: Path) -> Path:
    """Emit the tables and figures into `dest` for the README to embed."""
    raise NotImplementedError("implemented per plan: phase 4")
