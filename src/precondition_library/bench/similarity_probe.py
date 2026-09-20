"""Whether a similarity scorer can tell which resolution a state needs, from the text.

Issue #104's measurement, and the reason it exists: filling arm 2's `Similarity` seam with an
embedding model would make the baseline fairer *and* might make Claim 2's comparison come out
against predicate dispatch. On a fault family whose states are well separated by meaning, a
semantic scorer should do well precisely where probes have no advantage -- which the design spec
already names as the open risk that could kill the claim. So the question is measured before the
seam is swapped, not after.

**WARNING: the candidate text here is the wrong one, and the figure it reports is not the
baseline.** This module crosses each pair with its intent's declared resolutions and scores the
request against each resolution's **`rationale`** -- the intent designer's explanation. A dispatcher
compares against `_program_text(program)`: a program's `intent` plus its predicate descriptions.
Those are different texts, and they give opposite conclusions on the shipped scorer:

    request vs rationale : AUC 0.6755   <- what this module reports
    request vs program   : AUC 0.4778   <- what arm 2 actually does, and it is below chance

The rationales are more mutually distinct (mean pairwise token overlap 0.155) than the artifact
texts (0.312), so this module flatters the scorer by ~0.2 AUC. **Do not quote its number as the
baseline.** Issue #116 carries the finding, the cause -- `program.intent` is the intent *name*, a
constant across a fault's resolutions, and unweighted Jaccard is dominated by the shared
boilerplate -- and the fix. It also withdraws the conclusion drawn from this number, that a semantic
scorer has little headroom here: on the corrected evidence the scorer has almost no signal, so the
case for an embedding model is stronger rather than weaker.

What the module is still good for: comparing scorers **against each other** on one fixed set of
candidate texts, which is the reason it takes a mapping and not one scorer. Its cross-scorer
comparison is sound; its absolute value is not a dispatch measurement.

**Informational, never gated.** Like the text control's informed boundary, this reports a number
rather than asserting a threshold. A threshold on a proxy measurement would turn an exploratory
figure into a claim, which is the failure this repository keeps a rule about.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..similarity import Similarity
from ..tasks.intent import ResolutionVariant
from ..tasks.registry import ambiguous_intents
from ..tasks.state_grid import STATE_GRID
from .pairs import LabelledPair, labelled_pairs
from .textcontrol import roc_auc

PROBE_SEEDS: tuple[int, ...] = (0, 1, 2, 3)
"""The seeds states are crossed with. **Not the pre-registered plan** -- this is an exploratory
probe, and naming it separately keeps a reader from taking its output for the eval split."""


def discrimination_scores(
    pairs: Sequence[LabelledPair],
    variants: Sequence[ResolutionVariant],
    scorer: Similarity,
) -> tuple[list[float], list[bool]]:
    """`(score, is-this-the-correct-resolution)` for every (pair, resolution) crossing.

    The negatives do real work: a pair whose `correct_variant` is `None` has **no** correct
    resolution, so every crossing of it is negative and a scorer that always ranks something
    highly is caught by them rather than passing on the positive pairs alone.
    """
    scores: list[float] = []
    positives: list[bool] = []
    for pair in pairs:
        for variant in variants:
            scores.append(scorer(pair.task_text, variant.rationale))
            positives.append(pair.correct_variant == variant.id)
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


def discrimination_auc(
    pairs: Sequence[LabelledPair],
    variants: Sequence[ResolutionVariant],
    scorer: Similarity,
) -> float | None:
    """The AUC of `scorer` over `pairs` crossed with `variants`, or `None` if undecidable."""
    scores, positives = discrimination_scores(pairs, variants, scorer)
    if not positives or all(positives):
        return None
    return roc_auc(scores, positives)


def compare_scorers(
    scorers: Mapping[str, Similarity],
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
        for intent in ambiguous_intents():
            states = list(STATE_GRID[intent.name].values())
            pairs = labelled_pairs(intent, states, list(seeds))
            pairs_seen += len(pairs)
            found_scores, found_positives = discrimination_scores(pairs, intent.variants, scorer)
            scores.extend(found_scores)
            positives.extend(found_positives)
        auc = roc_auc(scores, positives) if positives and not all(positives) else None
        findings.append(
            ScorerDiscrimination(
                scorer=name,
                auc=auc,
                pairs=pairs_seen,
                comparisons=len(scores),
            )
        )
    return findings
