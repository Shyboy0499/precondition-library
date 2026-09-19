"""Whether a similarity scorer can tell which resolution a state needs, from the text.

Issue #104's measurement, and the reason it exists: filling arm 2's `Similarity` seam with an
embedding model would make the baseline fairer *and* might make Claim 2's comparison come out
against predicate dispatch. On a fault family whose states are well separated by meaning, a
semantic scorer should do well precisely where probes have no advantage -- which the design spec
already names as the open risk that could kill the claim. So the question is measured before the
seam is swapped, not after.

**What this measures, and what it does not.** Each pair is crossed with each of its intent's
declared resolutions, the scorer scores the pair's request text against that resolution's
`rationale`, and the AUC asks how often a correct resolution scores above an incorrect one. That
answers *is this fault family separable by meaning* -- the constructive question -- and it is
**not** the dispatch AUC the benchmark reports, which scores compiled program texts. A scorer can
separate rationales and still fail on programs; the reverse is possible too. Read the number as
evidence about whether a swap is worth trying, not as a result.

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
