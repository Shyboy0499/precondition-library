"""Choosing which stored program to replay. This module is the experiment.

Arms 2 and 3 differ only in the function they call here. Everything downstream
of a successful choice is identical — same runtime, same guard, same checker —
so any difference in outcome is attributable to the dispatch mechanism rather
than to the rest of the pipeline.
"""

from __future__ import annotations

from ..library import Library
from ..program import Program


def dispatch_semantic(signature, lib: Library) -> Program | None:
    """Arm 2: nearest program by intent embedding, above a similarity floor.

    The threshold is a tunable, and tuning it is a fair thing to do before
    comparing arms — an untuned control arm would be a straw man. The chosen
    threshold must be recorded in the ledger so the comparison stays auditable.
    """
    raise NotImplementedError("implemented per plan: phase 2")


def dispatch_preconditions(signature, lib: Library, env) -> Program | None:
    """Arm 3: the first program whose executable preconditions accept `env`.

    Ordering matters when several programs accept the same state; candidates are
    ranked by how specific their preconditions are, so a general program cannot
    shadow a targeted one.
    """
    raise NotImplementedError("implemented per plan: phase 2")
