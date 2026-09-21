"""Whether a similarity scorer can tell which resolution a state needs, from the text.

Issue #104's measurement, and the reason it exists: filling arm 2's `Similarity` seam with an
embedding model would make the baseline fairer *and* might make Claim 2's comparison come out
against predicate dispatch. On a fault family whose states are well separated by meaning, a
semantic scorer should do well precisely where probes have no advantage -- which the design spec
already names as the open risk that could kill the claim. So the question is measured before the
seam is swapped, not after.

The candidate text is the one a dispatcher actually scores. `program_text_candidates` calls
`library._program_text` -- the same text arm 2 compares against -- rather than restating it, so the
probe cannot come to measure a different text than the one it is about. On the shipped
`lexical_similarity`, over the ambiguous subset -- the committed gold programs crossed with the
probe's seeds -- the pooled figure is:

    AUC 0.5340, strict top-1 23/48 (chance for 3 candidates is 0.33)

with the two intents far apart (`restore_submodule_state` 0.6299 and 12-of-24, against
`sync_fork_with_upstream` 0.4965 and 11-of-24), so the pooled number describes neither of them
(ADR-0003). Those figures are printed by `tests/test_similarity_probe.py -q -s -k pooled_baseline`;
this docstring is the convenience and that test is the measurement, so a change to the artifact
text moves the numbers there first. On `sync_fork_with_upstream` the arm is at chance, and that is
issue #116's finding: the shipped scorer has almost no signal on this fault family. `program.intent`
is the intent *name* -- a constant across a fault's resolutions -- and unweighted Jaccard over token
sets is dominated by the boilerplate every resolution shares, so a correct and an incorrect
resolution score alike. It also withdraws the conclusion drawn from the earlier figure, that a
semantic scorer has little headroom here: on this evidence the case for swapping an embedding model
into the seam is stronger, not weaker.

The first version of this module scored the request against each resolution's **`rationale`**
instead. Rationales are more mutually distinct than the artifact texts, so it reported AUC 0.6755 --
a figure that flatters the scorer and supports the opposite conclusion. `rationale_candidates` keeps
that source reachable as a **diagnostic**, and `test_the_two_candidate_sources_disagree` fails if
the two stop differing, so the substitution cannot be repeated quietly. Anything reported as the
baseline must come from `program_text_candidates`. The record of the defect is in issue #116 and
spec revision 31.

What the module is best for: comparing scorers **against each other** on one fixed set of candidate
texts, which is why it takes a mapping and not one scorer.

**Informational, never gated.** Like the text control's informed boundary, this reports a number
rather than asserting a threshold. A threshold on a proxy measurement would turn an exploratory
figure into a claim, which is the failure this repository keeps a rule about.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
    failing: measured on the ambiguous subset, the merged mapping gave AUC 0.6980 and top-1 18/48,
    against the correct 0.5340 and 23/48 for the same scorer and pairs. Pooling across intents is
    legitimate, but it has to pool *per-intent crossings*, which is what `compare_scorers` does.
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
) -> tuple[list[float], list[bool]]:
    """`(score, is-this-the-correct-resolution)` for every (pair, candidate) crossing.

    The negatives do real work: a pair whose `correct_variant` is `None` has **no** correct
    resolution, so every crossing of it is negative and a scorer that always ranks something highly
    is caught by them rather than passing on the positive pairs alone.
    """
    _require_one_intent(pairs)
    scores: list[float] = []
    positives: list[bool] = []
    for pair in pairs:
        for variant_id, text in candidates.items():
            scores.append(scorer(pair.task_text, text))
            positives.append(pair.correct_variant == variant_id)
    return scores, positives


@dataclass(frozen=True)
class ScorerDiscrimination:
    """One scorer's discrimination over the probe's crossings, with its denominators."""

    scorer: str
    auc: float | None
    """`None` when the crossings are a single class, which `roc_auc` refuses. Reported as
    `None` rather than 0.0 so an uninformative probe cannot be read as a measured zero."""
    pairs: int
    comparisons: int
    decided: int
    """Pairs where the correct resolution scored strictly highest, pooled over the intents -- the
    argmax dispatch actually takes, and therefore the operative number. Reported beside the AUC
    because the two can disagree: IDF weighting over these texts raises the AUC while lowering
    this (ADR-0003)."""
    decidable: int
    """Pairs that have a correct resolution, so `decided` has a denominator. The negative pairs
    are in `pairs` and not here: no resolution is right for them, so there is no decision to get
    right."""


def discrimination_auc(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
) -> float | None:
    """The AUC of `scorer` over `pairs` crossed with `candidates`, or `None` if undecidable."""
    scores, positives = discrimination_scores(pairs, candidates, scorer)
    if not positives or all(positives):
        return None
    return roc_auc(scores, positives)


def top1_accuracy(
    pairs: Sequence[LabelledPair],
    candidates: Mapping[str, str],
    scorer: Similarity,
) -> tuple[int, int]:
    """`(pairs where the correct candidate scored strictly highest, pairs with a correct answer)`.

    Top-1 is what dispatch actually does -- it takes the argmax above a threshold -- so it is the
    headline number, with the AUC as the ranking-quality view behind it. Strictly highest, because a
    tie is not a decision: three candidates whose texts share a constant prefix score identically,
    and counting ties as wins would report a coin flip as 100%.
    """
    _require_one_intent(pairs)
    decided = 0
    total = 0
    for pair in pairs:
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
) -> list[ScorerDiscrimination]:
    """Run every scorer over the same pairs and report each one's discrimination.

    The pairs come from the declared state grid rather than from built sandboxes, so the
    comparison is cheap enough to run whenever a candidate scorer is proposed -- which is the
    point: the measurement has to be cheap or the swap gets decided on enthusiasm.
    """
    findings: list[ScorerDiscrimination] = []
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
                    f"intents needs program texts for every one of them, or the denominators are "
                    f"not the same comparison. Supplied: {sorted(candidates_by_intent)}"
                )
            candidates = candidates_by_intent[intent.name]
            states = list(STATE_GRID[intent.name].values())
            pairs = labelled_pairs(intent, states, list(seeds))
            pairs_seen += len(pairs)
            found_scores, found_positives = discrimination_scores(pairs, candidates, scorer)
            scores.extend(found_scores)
            positives.extend(found_positives)
            intent_decided, intent_decidable = top1_accuracy(pairs, candidates, scorer)
            decided += intent_decided
            decidable += intent_decidable
        auc = roc_auc(scores, positives) if positives and not all(positives) else None
        findings.append(
            ScorerDiscrimination(
                scorer=name,
                auc=auc,
                pairs=pairs_seen,
                comparisons=len(scores),
                decided=decided,
                decidable=decidable,
            )
        )
    return findings
