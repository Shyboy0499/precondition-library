"""A measurement of how far the request text alone gets a dispatcher.

The original flaw was a single fixed sentence per fault: the text *was* the class
label, so a dispatcher that read only the text could not mis-fire and the primary
claim was untestable. Tasks 1-8 removed the channel from state to wording entirely,
which made the text *mathematically incapable* of predicting the resolution -- and
so made a "does the text leak the answer?" control unable to fail, which is
indistinguishable from a control that passes.

The fix is to make wording genuinely depend on the situation (an intent's
`variant_phrasings`, sampled through `IntentSpec.task_text(seed, state)`) and then
*measure* how much a text-only dispatcher gets. A request can arrive through two
declared channels, and they answer different questions:

  uninformed  the shared `phrasings` distribution, sampled with no state, so the
              text cannot carry the resolution. This is the regime the primary
              claim is measured in, and `LEAKAGE_CEILING` is its tripwire: an AUC
              above it means the shared distribution has started leaking the
              answer.
  informed    a variant's `variant_phrasings` entry, wording that reveals the
              situation. A high AUC is expected here and is not a defect: it is
              the boundary condition, where the wording nearly gives the answer
              away and the mechanism is not needed at all.

Pooling the two produces a number that describes neither: it averages a regime in
which the text is the answer in disguise with one in which it is noise. An earlier
revision of this module did exactly that, with a single 0.99 ceiling. The control
now reports the regimes separately.

The classifier is deliberately simple: a bag-of-words logistic regression over word
counts. The question is whether the text *can* be sufficient, not whether a
sophisticated model could exploit it -- if even a linear model separates the classes,
the flaw is proven, and a stronger model would only widen the separation.

`tests/test_task_text_is_not_a_label.py` pins three things: a positive control that
the detector fires on informed wording that fully determines the answer, the real
assertion that the registered intents' *uninformed* wording does not leak it, and a
reported -- not gated -- measurement of the informed boundary. The measured AUC per
intent is the deliverable, not the pass/fail.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .pairs import LabelledPair

LEAKAGE_CEILING = 0.65
"""AUC above which uninformed wording is judged to be leaking the resolution.

Applies to the unaffected channel only. The informed channel is expected to
score high and is reported without a gate: it is the boundary condition, not a
defect. An earlier revision of this module applied a single 0.99 ceiling to both
channels pooled, which produced a number that described neither regime.
"""


def _tokens(text: str) -> list[str]:
    return [token for token in "".join(c.lower() if c.isalnum() else " " for c in text).split()]


def _counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _softmax(scores: Sequence[float]) -> list[float]:
    top = max(scores)
    exps = [math.exp(score - top) for score in scores]
    total = sum(exps)
    return [value / total for value in exps]


@dataclass
class TextOnlyClassifier:
    """Bag-of-words logistic regression trained by full-batch-free gradient descent.

    Multinomial with mean-squared-free cross-entropy updates. Small enough to
    read in one sitting on purpose: the control's job is to be obviously not
    clever, so that a separation it finds is credible.
    """

    labels: list[str]
    weights: dict[str, list[float]]
    bias: list[float]

    @classmethod
    def fit(
        cls,
        texts: Sequence[str],
        labels: Sequence[str],
        *,
        learning_rate: float = 0.5,
        epochs: int = 400,
    ) -> TextOnlyClassifier:
        if len(texts) != len(labels):
            raise ValueError("texts and labels must be the same length")
        classes = sorted(set(labels))
        if len(classes) < 2:
            raise ValueError("need at least two classes to train a classifier")
        index = {label: position for position, label in enumerate(classes)}
        vocabulary = sorted({token for text in texts for token in _tokens(text)})
        weights = {token: [0.0] * len(classes) for token in vocabulary}
        bias = [0.0] * len(classes)

        for _ in range(epochs):
            for text, label in zip(texts, labels, strict=True):
                counts = _counts(text)
                scores = [
                    bias[k] + sum(weights[token][k] * n for token, n in counts.items())
                    for k in range(len(classes))
                ]
                probabilities = _softmax(scores)
                target = index[label]
                for k in range(len(classes)):
                    error = probabilities[k] - (1.0 if k == target else 0.0)
                    bias[k] -= learning_rate * error
                    for token, n in counts.items():
                        weights[token][k] -= learning_rate * error * n
        return cls(labels=classes, weights=weights, bias=bias)

    def predict_proba(self, text: str) -> dict[str, float]:
        counts = _counts(text)
        scores = [
            self.bias[k]
            + sum(
                self.weights.get(token, [0.0] * len(self.labels))[k] * n
                for token, n in counts.items()
            )
            for k in range(len(self.labels))
        ]
        return dict(zip(self.labels, _softmax(scores), strict=True))


def roc_auc(scores: Sequence[float], positives: Sequence[bool]) -> float:
    """Rank-based AUC with ties handled by average rank.

    Implemented rather than imported: scikit-learn is not a dependency of this
    project, and a control that needs a new dependency to run is a control that
    gets skipped.
    """
    if len(scores) != len(positives):
        raise ValueError("scores and positives must be the same length")
    positive_count = sum(positives)
    negative_count = len(positives) - positive_count
    if positive_count == 0 or negative_count == 0:
        raise ValueError("AUC is undefined with only one class present")

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1

    rank_sum = sum(rank for rank, is_positive in zip(ranks, positives, strict=True) if is_positive)
    return (rank_sum - positive_count * (positive_count + 1) / 2) / (
        positive_count * negative_count
    )


@dataclass(frozen=True)
class LeakageVerdict:
    auc: float
    ceiling: float
    classes: list[str]
    n_train: int
    n_eval: int
    regime: str
    """Which channel this verdict covered: 'uninformed', 'informed', or 'pooled'."""

    @property
    def leaks(self) -> bool:
        return self.auc > self.ceiling

    def describe(self) -> str:
        return (
            f"{self.regime} text-only AUC {self.auc:.3f} over {len(self.classes)} classes "
            f"(train n={self.n_train}, eval n={self.n_eval}, ceiling {self.ceiling}); "
            + ("wording leaks the resolution" if self.leaks else "no leak at this sample size")
        )


def leakage_verdict(
    pairs: Iterable[LabelledPair],
    *,
    train_seeds: Sequence[int],
    eval_seeds: Sequence[int],
    informed: bool | None = None,
    ceiling: float = LEAKAGE_CEILING,
) -> LeakageVerdict:
    """Train on the text from one seed set, evaluate on a disjoint one.

    `informed` selects the regime: None pools every pair, False measures only the
    unaffected, uninformed channel, and True only the informed boundary. A
    filter that leaves nothing to score raises rather than returning a verdict
    over an empty set, because a verdict with no data behind it would read as a
    clean bill of health.

    Only positive pairs are used: a negative pair's "answer" is "fire nothing",
    which is not a resolution a text classifier could be said to get right or
    wrong, and including it would inflate or deflate AUC for reasons unrelated to
    what is being measured.

    One-vs-rest AUC is averaged over the eval classes. The label set is tiny and
    the control's only job is to detect text that gives the resolution away.
    """
    if informed is None:
        regime = "pooled"
    else:
        regime = "informed" if informed else "uninformed"

    train_set = set(train_seeds)
    eval_set = set(eval_seeds)
    materialised = [p for p in pairs if informed is None or p.informed is informed]
    if not materialised:
        raise ValueError(f"no {regime} pairs to measure; the regime filter left nothing")
    train = [p for p in materialised if p.seed in train_set and not p.is_negative]
    evaluation = [p for p in materialised if p.seed in eval_set and not p.is_negative]
    if not train or not evaluation:
        raise ValueError("need non-empty train and eval sets of positive pairs")

    model = TextOnlyClassifier.fit(
        [p.task_text for p in train],
        [p.correct_variant for p in train if p.correct_variant is not None],
    )

    classes = sorted({p.correct_variant for p in evaluation if p.correct_variant is not None})
    aucs: list[float] = []
    for cls in classes:
        scores = [model.predict_proba(p.task_text).get(cls, 0.0) for p in evaluation]
        positives = [p.correct_variant == cls for p in evaluation]
        if all(positives) or not any(positives):
            continue
        aucs.append(roc_auc(scores, positives))
    if not aucs:
        raise ValueError("every eval class is degenerate; AUC is undefined")

    return LeakageVerdict(
        auc=sum(aucs) / len(aucs),
        ceiling=ceiling,
        classes=classes,
        n_train=len(train),
        n_eval=len(evaluation),
        regime=regime,
    )
