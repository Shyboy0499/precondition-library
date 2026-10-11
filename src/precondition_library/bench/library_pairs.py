"""Figure 1's pair outcomes from a compiled library, through its own matchers (issue #162).

`bench.coverage` turns per-pair dispatch outcomes into the primary metric, and
`bench.primary` turns those into Figure 1, but neither builds the outcomes. The pieces that
did -- `coverage.arm2_outcomes` (one text per variant) and `coverage.arm3_outcomes` (a
caller-supplied decision) -- fit hand-written gold, not a compiled library. A compiled
library holds several programs per variant, admits programs across intents, and is
dispatched by `Library.match_semantic` with its own eligibility filter and tie-break. So
the first real Figure 1 needed a driver outside the repository. This module is that driver.

**The pair-level arms are the arms the episodes run.** Every outcome comes from the
library's own matcher on a real sandbox, with the request and signature built the way
`bench.run` builds them:

* arm 2 -- `Library.match_semantic`, **unthresholded**, so `coverage.sweep` sees every
  score the library's similarity (and reranker, if any) produced;
* arm 3 -- `Library.match_preconditions`, the first (most specific) program;
* arm 2b -- `Library.rank_soft`, the top program and its score, swept like arm 2;
* arm 2c -- `Library.match_intent_key`, which abstains on a key whose programs disagree.

**The pairs (ADR-0022).** For each seed, the fault-free sandbox and every measured fault's
state are built, and each measured intent's request at that seed is paired with:

* its own fault's state, which its rule labels -- usually a positive pair;
* the **fault-free sandbox**, which no rule labels -- the negative every dispatcher must
  refuse; and
* another fault's state **only when this intent's rule labels it** -- an overlap state,
  as admission defines one (ADR-0019) -- which is then a positive with that label.

Another fault's state that the intent leaves **unlabelled** is not a pair. It would pose a
request about one family in a repository whose problem belongs to another, which no
episode ever does, and arm 3 -- which reads only the environment, by design -- would fire
that family's program there and be scored wrong for ignoring a request it is built to
ignore. That is not the comparison Claim 2 makes. The fault-free sandbox is the negative,
and it is one environment however many seeds are crossed with it: one state, many
requests.

**Only the uninformed regime.** The request is `intent.task_text(seed)`, the one the
episodes send (`FaultSpec.task_text` delegates to it). The informed channel would put
pairs of both regimes into one list, and the metric never pools them (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from ..library import Library
from ..program import Program
from ..sandbox import Sandbox
from ..signatures import StateFingerprint, TaskSignature
from ..tasks.faults import build_sandbox
from ..tasks.intent import IntentSpec
from ..tasks.registry import ambiguous_intents
from .coverage import PairOutcome
from .pairs import LabelledPair, label

FAULT_FREE = "fault-free"
"""The `environment` name of the fault-free sandbox's pairs."""

SOFT_VOTE = "arm 2b (soft vote)"
INTENT_KEY = "arm 2c (intent key)"


class RankedProgram(BaseModel):
    """One program in a request's text ranking, with what a later reader needs to re-decide.

    Recorded per pair so the hybrid arm (#265) can be derived from this pass instead of rebuilding
    every environment: the hybrid's decision at any `(k, threshold)` is a walk down this list, and
    the walk needs each program's id, score and declared resolution -- nothing else.
    """

    id: str
    variant: str | None
    score: float


class LibraryPair(BaseModel):
    """One labelled pair, with the environment it was built in and what the arms saw there."""

    pair: LabelledPair
    environment: str
    """`FAULT_FREE`, or the name of the fault whose state the sandbox holds."""
    accepted: tuple[str, ...] = ()
    """Program ids whose preconditions hold in this environment, in arm 3's firing order.

    Empty on a negative pair, which is the gate's whole point. Recorded because arm 3's decision is
    computed here anyway -- `match_preconditions` evaluates every admitted program -- and a hybrid
    needs the *accepted set*, not only the winner that set produced (issue #265).
    """
    ranked: tuple[RankedProgram, ...] = ()
    """This request's text ranking of the admitted programs, best first and unthresholded.

    Complete rather than top-1: `score_all` scores every admitted program either way, so a wider
    limit re-trims a list that was already computed. The hybrid sweeps `k` over it and applies a
    retrieval floor of its own to the scores."""


class LibraryPairOutcomes(BaseModel):
    """Every dispatcher's outcome on one set of pairs, index-aligned with `pairs`."""

    library_hash: str
    pairs: list[LibraryPair]
    arm2: list[PairOutcome]
    arm3: list[PairOutcome]
    soft_vote: list[PairOutcome]
    intent_key: list[PairOutcome]

    def baselines(self) -> dict[str, list[PairOutcome]]:
        """Arms 2b and 2c in the shape `bench.primary.primary_report` takes."""
        return {SOFT_VOTE: self.soft_vote, INTENT_KEY: self.intent_key}


@dataclass(frozen=True)
class _EnvironmentDecisions:
    """What the state-reading arms decide in one sandbox; the same for every request."""

    state: StateFingerprint
    target: str
    arm3: str | None
    soft_variant: str | None
    soft_score: float | None
    accepted: tuple[str, ...] = ()
    """The ids whose preconditions hold here, in `match_preconditions`' order (issue #265)."""


def _measured_intents(faults: Sequence[str]) -> list[IntentSpec]:
    """The ambiguous intent of each fault, in order, or a refusal naming the measurable ones."""
    measured = {intent.fault: intent for intent in ambiguous_intents()}
    unknown = [fault for fault in faults if fault not in measured]
    if unknown:
        raise ValueError(
            f"{unknown} have no registered ambiguous intent, so they cannot be measured; "
            f"measurable faults: {sorted(measured)}"
        )
    if len(set(faults)) != len(faults):
        raise ValueError(f"faults repeat: {list(faults)}")
    return [measured[fault] for fault in faults]


def _unthresholded(library: Library) -> Library:
    """The same arm 2 with no floor, so the sweep, not the library, picks the threshold."""
    return Library(
        library.root,
        similarity=library.similarity,
        threshold=float("-inf"),
        reranker=library.reranker,
        rerank_k=library.rerank_k,
    )


def _decide(library: Library, box: Sandbox) -> _EnvironmentDecisions:
    """Run the state-reading arms once per sandbox: they never read the request."""
    accepted: list[Program] = library.match_preconditions(box)
    ranked = library.rank_soft(box)
    return _EnvironmentDecisions(
        state=StateFingerprint.observe(box),
        target=str(box.work),
        arm3=accepted[0].variant if accepted else None,
        soft_variant=ranked[0].program.variant if ranked else None,
        soft_score=ranked[0].score if ranked else None,
        accepted=tuple(program.id for program in accepted),
    )


def is_pair(environment: str, intent: IntentSpec, pair: LabelledPair) -> bool:
    """ADR-0022's rule: whether `intent`'s request in `environment` is a pair at all.

    The fault-free sandbox and the intent's own fault always are. Another fault's state is
    only when the intent labels it -- an overlap state (ADR-0019).
    """
    if environment in (FAULT_FREE, intent.fault):
        return True
    return pair.correct_variant is not None


def _outcome(pair: LabelledPair, variant: str | None, score: float | None) -> PairOutcome:
    return PairOutcome(
        correct_variant=pair.correct_variant,
        acceptable_variants=pair.acceptable_variants,
        fired_variant=variant,
        score=score,
        informed=pair.informed,
    )


def library_pair_outcomes(
    library: Library, faults: Sequence[str], seeds: Sequence[int]
) -> LibraryPairOutcomes:
    """Build every pair's sandbox and dispatch it through `library`'s own matchers.

    `library` must carry a predicate evaluator (arms 3 and 2b need one) and is read, never
    written: nothing here compiles, demotes or quarantines. Its configured `threshold` and
    `soft_threshold` are deliberately not applied -- the outcomes record what each arm
    *would* fire and at what score, and `coverage.sweep` applies every threshold.
    """
    if library.evaluate_preconditions is None:
        raise ValueError(
            "arms 3 and 2b need a predicate evaluator; pass "
            "Library(root, evaluate_preconditions=...)"
        )
    if not seeds:
        raise ValueError("no seeds, so no pairs")
    intents = _measured_intents(faults)
    semantic = _unthresholded(library)

    result = LibraryPairOutcomes(
        library_hash=library.library_hash(),
        pairs=[],
        arm2=[],
        arm3=[],
        soft_vote=[],
        intent_key=[],
    )
    # A limit wide enough to return every admitted program: `score_all` scores them all anyway,
    # so this trims nothing off the cost and leaves the complete ranking for the hybrid (#265).
    every_program = len(library.load_all())
    for seed in seeds:
        for environment, injected in [(FAULT_FREE, []), *((f, [f]) for f in faults)]:
            box = build_sandbox(seed, injected)
            try:
                decided = _decide(library, box)
            finally:
                box.destroy()
            for intent in intents:
                pair = label(intent, seed, decided.state, uninformed=True)
                if not is_pair(environment, intent, pair):
                    continue
                signature = TaskSignature(
                    intent=pair.task_text, fingerprint=decided.state, target=decided.target
                )
                ranked = semantic.match_semantic(signature, limit=every_program)
                keyed = library.match_intent_key(signature)

                result.pairs.append(
                    LibraryPair(
                        pair=pair,
                        environment=environment,
                        accepted=decided.accepted,
                        ranked=tuple(
                            RankedProgram(
                                id=item.program.id,
                                variant=item.program.variant,
                                score=item.score,
                            )
                            for item in ranked
                        ),
                    )
                )
                result.arm2.append(
                    _outcome(pair, ranked[0].program.variant, ranked[0].score)
                    if ranked
                    else _outcome(pair, None, None)
                )
                result.arm3.append(_outcome(pair, decided.arm3, None))
                result.soft_vote.append(_outcome(pair, decided.soft_variant, decided.soft_score))
                result.intent_key.append(_outcome(pair, keyed[0].variant if keyed else None, None))
    return result
