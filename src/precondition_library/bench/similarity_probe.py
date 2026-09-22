"""Whether a similarity scorer can tell which resolution a state needs, from the text.

Issue #104's measurement, and the reason it exists: filling arm 2's `Similarity` seam with an
embedding model would make the baseline fairer *and* might make Claim 2's comparison come out
against predicate dispatch. On a fault family whose states are well separated by meaning, a
semantic scorer should do well precisely where probes have no advantage -- which the design spec
already names as the open risk that could kill the claim. So the question is measured before the
seam is swapped, not after.

**The measurement is per regime, and the informed regime is the baseline.** Every pair records the
channel its text arrived through; the two channels answer different questions, and
`bench/textcontrol.py` is the authority on why. On the shipped `lexical_similarity`, over the
ambiguous subset -- the committed gold programs crossed with the probe's seeds 0-3, which are
**hand-written gold on an exploratory probe seed set, not the pre-registered split**:

    informed    AUC 0.6172, strict top-1 15/24 (63%), chance for three candidates 33%
    uninformed  AUC 0.5000, strict top-1 8/24 (33%) -- chance, by construction

The informed figure is the boundary condition and the genuine measurement, and it is what the
baseline has to be quoted at, with the per-intent breakdown ADR-0003 requires:
`restore_submodule_state` 0.8125 and 8-of-12, `sync_fork_with_upstream` 0.6007 and 7-of-12. The
uninformed figure is the plumbing tripwire `bench/textcontrol.py` designed: the sampler never
consults state, so every positive has a negative with an identical score and the AUC is 0.500 for
any classifier and any phrasing list. A departure from 0.500 there means state has begun reaching
the sampler -- the regression that restored the original flaw -- and the negative pairs belong to
that regime rather than to baseline material.

**The regimes are never pooled, and there is no pooled mode.** An earlier revision of this module
scored every pair regardless of channel and reported one number (AUC 0.5340, strict top-1 23/48);
ADR-0003's accepted baseline was the same construction at 0.5722 and 23/48, before the gold
descriptions were rewritten in revision 35. Averaging a regime in which the text is the answer in
disguise with one in which it is noise by construction describes neither (`bench/textcontrol.py`),
and the pooled figure hides the spread that is the actual result. The functions here take a required
`regime`, `compare_scorers` reports one row per regime, and nothing returns a combined number.

The candidate text is the one a dispatcher actually scores. `program_text_candidates` calls
`library._program_text` -- the same text arm 2 compares against -- rather than restating it, so the
probe cannot come to measure a different text than the one it is about.

The first version of this module scored the request against each resolution's **`rationale`**
instead. Rationales are more mutually distinct than the artifact texts, so it reported AUC 0.6755 --
a figure that flatters the scorer and supports the opposite conclusion. `rationale_candidates` keeps
that source reachable as a **diagnostic**, and `test_the_two_candidate_sources_disagree` fails if
the two stop differing, so the substitution cannot be repeated quietly. Anything reported as the
baseline must come from `program_text_candidates`. The record of the defect is in issue #116 and
spec revision 31.

The regime correction also re-reads issue #116's conclusion. That revision found the shipped scorer
with almost no signal on `sync_fork_with_upstream` and drew from it that the case for an embedding
behind the seam is stronger. The no-signal figure was a pooled one: on the informed channel the
same scorer scores 0.6007 and 7-of-12 (58%) on that intent, and the uninformed channel is chance by
construction. So the conclusion does not follow from the informed baseline; whether an embedding
helps is measured on the same regime split in `tests/test_embedding_similarity.py`.

What the module is best for: comparing scorers **against each other** on one fixed set of candidate
texts within one regime, which is why it takes a mapping and not one scorer.

**Informational, never gated.** Like the text control's informed boundary, this reports a number
rather than asserting a threshold. A threshold on a proxy measurement would turn an exploratory
figure into a claim, which is the failure this repository keeps a rule about.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ..library import _program_text
from ..program import Program
from ..similarity import Similarity
from ..tasks.intent import IntentSpec
from ..tasks.registry import ambiguous_intents
from ..tasks.state_grid import STATE_GRID
from .pairs import LabelledPair, labelled_pairs
from .textcontrol import roc_auc

PROBE_SEEDS: tuple[int, ...] = (0, 1, 2, 3)
"""The seeds states are crossed with. **Not the pre-registered plan** -- this is an exploratory
probe, and naming it separately keeps a reader from taking its output for the eval split."""

Regime = Literal["informed", "uninformed"]
"""Which channel a request's text arrived through, from `LabelledPair.informed`."""

REGIMES: tuple[Regime, ...] = ("informed", "uninformed")
"""The two channels, informed first because it is the headline baseline.

The uninformed row is the plumbing tripwire `bench/textcontrol.py` designed: its text cannot carry
the resolution, so an AUC other than 0.500 there is a defect in the construction, not a measurement.
It is reported beside the baseline and never as one.
"""


def regime_of(pair: LabelledPair) -> Regime:
    """The channel `pair`'s text arrived through, read from the field that records it."""
    return "informed" if pair.informed else "uninformed"


def _pairs_in_regime(pairs: Sequence[LabelledPair], regime: Regime) -> list[LabelledPair]:
    """Keep one regime's pairs, and refuse a filter that leaves nothing to measure.

    Empty is an error rather than an empty result because a figure with no denominator behind it
    would read as a clean measurement. The regimes are never combined: filtering is the only way
    `regime` reaches the single-mapping functions, and there is no value meaning "both".
    """
    selected = [pair for pair in pairs if regime_of(pair) == regime]
    if not selected:
        raise ValueError(f"no {regime} pairs to measure; the regime filter left nothing")
    return selected


def program_text_candidates(programs: Sequence[Program]) -> dict[str, str]:
    """The candidate texts dispatch actually compares against, keyed by resolution.

    `_program_text` rather than a copy of it: the dispatcher scores a program's `intent` plus its
    predicate descriptions, and a second definition here would be free to drift from the one arm 2
    uses -- which is how this probe came to measure the wrong text in the first place (#116).

    A program with no `variant` is **excluded**, for two reasons that agree. It declares no
    resolution, so it cannot be the correct answer to anything; and a `None` key would compare
    equal to a negative pair's `correct_variant`, counting a program as correct for the pairs
    where nothing should fire at all. The library quarantines such a program on load for the same
    reason it cannot be scored here (issues #66, #69).
    """
    return {
        program.variant: _program_text(program)
        for program in programs
        if program.variant is not None
    }


def rationale_candidates(intent: IntentSpec) -> dict[str, str]:
    """Each resolution's `rationale`. **A diagnostic, not the measurement.**

    Kept because the two sources disagreeing is itself worth seeing -- see
    `test_the_two_candidate_sources_disagree` -- but a rationale is the intent designer's
    explanation, not the text a dispatcher compares, and it is more mutually distinct than the
    artifact (a figure `test_the_candidate_texts_pairwise_similarity_is_reported` prints for the
    artifact; the diagnostic prints the rationale's beside it). Anything reported as the baseline
    must come from `program_text_candidates`.
    """
    return {variant.id: variant.rationale for variant in intent.variants}


def _require_one_intent(pairs: Sequence[LabelledPair]) -> None:
    """Refuse a crossing that spans intents, because `candidates` cannot describe more than one.

    `candidates` is a `variant -> text` mapping with no intent attached, and variant ids are unique
    only *within* an intent. Handing these functions pairs from two intents therefore crosses each
    pair with resolutions that are not its own, and it reports a plausible number rather than
    failing: measured on the informed regime of the ambiguous subset, the merged mapping gave
    AUC 0.7722 and top-1 12/24, against the correct 0.6172 and 15/24 for the same scorer and pairs.
    Pooling across intents is legitimate, but it has to pool *per-intent crossings*, which is what
    `compare_scorers` does.
    """
    intents = {pair.intent for pair in pairs}
    if len(intents) > 1:
        raise ValueError(
            f"pairs span {len(intents)} intents ({sorted(intents)}), but one candidate mapping "
            f"cannot describe more than one: variant ids are unique only within an intent, so this "
            f"would score each pair against another intent's resolutions and return a number "
            f"instead of failing. Score each intent separately and pool the crossings, as "
            f"`compare_scorers` does."
        )


def discrimination_scores(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
    *,
    regime: Regime,
) -> tuple[list[float], list[bool]]:
    """`(score, is-this-the-correct-resolution)` for every (pair, candidate) crossing of a regime.

    `regime` is required and the pairs are filtered to it: informed and uninformed crossings are
    never pooled, because a number that averages a regime in which the text is the answer in
    disguise with one in which it is noise by construction describes neither. There is deliberately
    no "both" value to pass -- the pooled number is the defect this probe now refuses to produce.

    The negatives do real work inside the uninformed regime: a pair whose `correct_variant` is
    `None` has **no** correct resolution, so every crossing of it is negative and a scorer that
    always ranks something highly is caught by them rather than passing on the positive pairs
    alone. An informed pair always has a correct resolution -- informed wording exists only where
    one does -- so that regime has no negatives and its `decidable` equals its `pairs`.
    """
    selected = _pairs_in_regime(pairs, regime)
    _require_one_intent(selected)
    scores: list[float] = []
    positives: list[bool] = []
    for pair in selected:
        for variant_id, text in candidates.items():
            scores.append(scorer(pair.task_text, text))
            positives.append(pair.correct_variant == variant_id)
    return scores, positives


@dataclass(frozen=True)
class ScorerDiscrimination:
    """One scorer's discrimination over one regime's crossings, with its denominators."""

    scorer: str
    regime: Regime
    """Which channel this row covers. Rows are never aggregated across regimes: the informed row is
    the baseline and the uninformed row is the plumbing tripwire reported beside it."""
    auc: float | None
    """`None` when the crossings are a single class, which `roc_auc` refuses. Reported as
    `None` rather than 0.0 so an uninformative probe cannot be read as a measured zero."""
    pairs: int
    comparisons: int
    decided: int
    """Pairs where the correct resolution scored strictly highest, pooled over the intents within
    this regime -- the argmax dispatch actually takes, and therefore the operative number. Reported
    beside the AUC because the two can disagree: IDF weighting over these texts raises the AUC while
    lowering this (ADR-0003)."""
    decidable: int
    """Pairs that have a correct resolution, so `decided` has a denominator. The negative pairs are
    in `pairs` and not here: no resolution is right for them, so there is no decision to get right.
    They occur only in the uninformed regime, as its tripwire."""


def discrimination_auc(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
    *,
    regime: Regime,
) -> float | None:
    """The AUC of `scorer` over one regime of `pairs` crossed with `candidates`, or `None`.

    `regime` is required and the two regimes are never pooled; see `discrimination_scores`.
    """
    scores, positives = discrimination_scores(pairs, candidates, scorer, regime=regime)
    if not positives or all(positives):
        return None
    return roc_auc(scores, positives)


def top1_accuracy(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
    *,
    regime: Regime,
) -> tuple[int, int]:
    """`(pairs where the correct candidate scored strictly highest, pairs with a correct answer)`.

    Top-1 is what dispatch actually does -- it takes the argmax above a threshold -- so it is the
    headline number, with the AUC as the ranking-quality view behind it. Strictly highest, because a
    tie is not a decision: three candidates whose texts share a constant prefix score identically,
    and counting ties as wins would report a coin flip as 100%.

    `regime` is required and the two regimes are never pooled; see `discrimination_scores`.
    """
    selected = _pairs_in_regime(pairs, regime)
    _require_one_intent(selected)
    decided = 0
    total = 0
    for pair in selected:
        if pair.correct_variant is None:
            continue
        total += 1
        ranked = sorted(
            ((scorer(pair.task_text, text), variant_id) for variant_id, text in candidates.items()),
            key=lambda item: (-item[0], item[1]),
        )
        # Fewer than two candidates cannot be a decision: there is nothing to have beaten, so the
        # pair counts in the denominator and not the numerator rather than scoring a free win.
        if len(ranked) > 1 and ranked[0][1] == pair.correct_variant and ranked[0][0] > ranked[1][0]:
            decided += 1
    return decided, total


def compare_scorers(
    scorers: Mapping[str, Similarity],
    candidates_by_intent: Mapping[str, Mapping[str, str]],
    *,
    seeds: Sequence[int] = PROBE_SEEDS,
    regimes: Sequence[Regime] = REGIMES,
) -> list[ScorerDiscrimination]:
    """Run every scorer over the same pairs of each regime: one row per (regime, scorer).

    Rows come informed-first (`REGIMES`), because the informed channel is the claim's baseline and
    the uninformed one is the plumbing tripwire reported beside it. The two regimes are never
    combined: within a regime the crossings pool per intent, which ADR-0003 requires and the
    denominators on each row make checkable, but the regimes themselves are not added up.

    The pairs come from the declared state grid rather than from built sandboxes, so the
    comparison is cheap enough to run whenever a candidate scorer is proposed -- which is the
    point: the measurement has to be cheap or the swap gets decided on enthusiasm.
    """
    findings: list[ScorerDiscrimination] = []
    for regime in regimes:
        for name in sorted(scorers):
            scorer = scorers[name]
            scores: list[float] = []
            positives: list[bool] = []
            pairs_seen = 0
            decided = 0
            decidable = 0
            for intent in ambiguous_intents():
                if intent.name not in candidates_by_intent:
                    raise ValueError(
                        f"no candidate texts for intent {intent.name!r}; comparing scorers across "
                        f"intents needs program texts for every one of them, or the denominators "
                        f"are not the same comparison. Supplied: {sorted(candidates_by_intent)}"
                    )
                candidates = candidates_by_intent[intent.name]
                states = list(STATE_GRID[intent.name].values())
                pairs = _pairs_in_regime(labelled_pairs(intent, states, list(seeds)), regime)
                pairs_seen += len(pairs)
                found_scores, found_positives = discrimination_scores(
                    pairs, candidates, scorer, regime=regime
                )
                scores.extend(found_scores)
                positives.extend(found_positives)
                intent_decided, intent_decidable = top1_accuracy(
                    pairs, candidates, scorer, regime=regime
                )
                decided += intent_decided
                decidable += intent_decidable
            auc = roc_auc(scores, positives) if positives and not all(positives) else None
            findings.append(
                ScorerDiscrimination(
                    scorer=name,
                    regime=regime,
                    auc=auc,
                    pairs=pairs_seen,
                    comparisons=len(scores),
                    decided=decided,
                    decidable=decidable,
                )
            )
    return findings
