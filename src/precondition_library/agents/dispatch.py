"""Choosing which stored program to replay. This module is the experiment.

Arms 2 and 3 differ only in the function they call here. Everything downstream
of a successful choice is identical — same runtime, same guard, same checker —
so any difference in outcome is attributable to the dispatch mechanism rather
than to the rest of the pipeline.

Both functions below are deliberately trivial: each calls one matcher and reports
that matcher's verdict in a shared record. The arm-specific work — the ranking,
the threshold, the `admitted` filter, the precondition probes — lives in
`library.py`, behind the matcher. A re-rank, a second filter or a score
adjustment written *here* would be logic one arm gets and the other does not,
which is exactly the confound §4 of the design spec forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..library import Library
from ..program import Program
from ..sandbox import Sandbox
from ..signatures import TaskSignature


@dataclass(frozen=True)
class Dispatch:
    """What one arm decided, in the one shape both arms return.

    `program` is the chosen program, or `None` when nothing applies — the
    caller's fallback path, not an error. `score` is the number the mechanism
    selected with, carried unmodified; it is `None` for arm 3, which has no
    score, and for a miss on either arm. `reason` is a short human-readable
    verdict for the runner to record.

    Defined once rather than a return type per arm, so the runner and the ledger
    read a dispatch without branching on which arm produced it. The arms must
    differ in *one* function, not in what they report: a shape difference here
    would be the confound §4 of the design spec forbids.
    """

    program: Program | None
    score: float | None
    reason: str


def dispatch_semantic(signature: TaskSignature, lib: Library) -> Dispatch:
    """Arm 2: the nearest program by text similarity, above a similarity floor.

    "Text similarity" is the mechanism the arm is run with (lexical today, an
    embedding model behind the same seam as the intended replacement), and the
    text compared is the intent plus the fingerprint rendered as words, not the
    intent alone. The threshold is a tunable, and tuning it is a fair thing to do
    before comparing arms — an untuned control arm would be a straw man. The
    chosen threshold must be recorded in the ledger so the comparison stays
    auditable. `Library.match_semantic` returns each program with its score, so
    this function records a number it did not recompute.

    The body is a single call: the matcher does the ranking, the threshold and
    the `admitted` filter, and its first element is already the nearest program.
    Nothing here re-ranks, filters or adjusts — see the module docstring for why
    that is a constraint rather than a stylistic preference.
    """
    ranked = lib.match_semantic(signature)
    if not ranked:
        return Dispatch(None, None, "no admitted program above the similarity floor")
    best = ranked[0]
    return Dispatch(best.program, best.score, "nearest by text similarity")


def dispatch_preconditions(signature: TaskSignature, lib: Library, env: Sandbox) -> Dispatch:
    """Arm 3: the first program whose executable preconditions accept `env`.

    Ordering matters when several programs accept the same state; candidates are
    ranked by how specific their preconditions are, so a general program cannot
    shadow a targeted one. `Library.match_preconditions` does that ordering and
    the `admitted` filter, so its first element is already the choice. Nothing
    here re-ranks or filters.

    The score is `None`: arm 3 selects on a predicate verdict and has no number
    to report, and `bench/ledger.py` defines `dispatch_score` as arm 2's alone.
    A score leaking into arm 3's record would be a silent inconsistency between
    what the arm decided and what the ledger says it decided.
    """
    accepted = lib.match_preconditions(signature, env)
    if not accepted:
        return Dispatch(None, None, "no admitted program's preconditions held")
    return Dispatch(accepted[0], None, "first by precondition specificity")
