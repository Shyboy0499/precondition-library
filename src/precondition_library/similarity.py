"""How similar two pieces of text are: the seam arm 2 dispatches through.

Arm 2 chooses a program by *text similarity*, so the function that scores two
strings is part of that arm's definition rather than a helper beside it. It sits
behind `Similarity`, a one-method Protocol, so the mechanism can be replaced
without touching either arm: a real embedding model implements the same callable
and is injected in one place.

The implementation shipped here is deliberately lexical. It is a **proxy for
semantic similarity**, not semantic similarity itself: it compares surface forms,
so "discard the commits" and "throw away local history" score zero against each
other despite meaning the same thing. That ceiling is a property of the proxy and
is the honest description of what arm 2 was actually run with; an embedding
implementation behind the same Protocol is the intended replacement, and until
one exists the claim compares precondition dispatch against *text* similarity.

Tokenisation reuses the approach the project already has (`bench.textcontrol`):
lowercase, keep alphanumerics, split on everything else. A second, subtly
different tokeniser would let the dispatch comparison and the text control
disagree about what "the same words" means, which is a disagreement between two
parts of the experiment rather than a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


def tokenize(text: str) -> list[str]:
    """Lowercase, keep alphanumerics, split on everything else.

    One tokeniser for the whole project, shared with `bench.textcontrol` rather
    than copied there. The normalisation is also what makes the score
    independent of formatting: case, punctuation, and whitespace carry no signal,
    so a probe string and a sentence word the same tokens when they use the same
    words.
    """
    return [token for token in "".join(c.lower() if c.isalnum() else " " for c in text).split()]


class Similarity(Protocol):
    """A scoring function: `(query, candidate) -> score`.

    The score is expected in `[0, 1]`, where 1 is identical, so that a threshold
    is comparable across implementations. A Protocol rather than an abstract base
    class because a plain function satisfies it structurally -- the default
    `lexical_similarity` below is one -- and a future embedding model need only
    be callable, not inherit from anything here.
    """

    def __call__(self, query: str, candidate: str) -> float: ...


def lexical_similarity(query: str, candidate: str) -> float:
    """Jaccard overlap of the two texts' token sets, in `[0, 1]`.

    Chosen over a term-frequency cosine because it is bounded, symmetric, and has
    no weighting to tune: the only decision is how text is tokenised, and that is
    shared with the rest of the project. It reads surface overlap, nothing more --
    a paraphrase with no shared word scores 0.0, which is the proxy's ceiling and
    the reason an embedding implementation is the intended replacement.

    Two empty texts are not "identical": with no tokens there is no evidence of
    similarity, so the score is 0.0 rather than 1.0.
    """
    query_tokens = set(tokenize(query))
    candidate_tokens = set(tokenize(candidate))
    if not query_tokens or not candidate_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)


@dataclass(frozen=True)
class SimilarityUsage:
    """What a similarity implementation spent, in its **own** currency.

    Zero for the lexical implementation, which spends nothing at all. An embedding model
    behind the same Protocol reports its own tokens and calls here, and they are never
    added to the LLM's `tokens_in`/`tokens_out`: a different currency at a different
    price, spent by one arm and not the others, so folding them in would make arm 2's
    cost depend on a model the other arms never call (issue #104).
    """

    tokens: int = 0
    calls: int = 0


class ReportsUsage(Protocol):
    """A `Similarity` that can also say what it has spent. **Optional, by design.**

    Deliberately not part of `Similarity`, so that seam stays a one-method callable:
    `lexical_similarity` is a plain function and satisfies it unchanged, and a caller
    that only needs scores never has to know usage exists. An embedding implementation
    satisfies both.
    """

    def usage(self) -> SimilarityUsage: ...


def similarity_usage(similarity: Similarity) -> SimilarityUsage:
    """What `similarity` has spent so far, or zero when it does not report usage.

    Zero rather than raising, because not reporting is the ordinary case: the shipped
    implementation is a function and there is nothing for it to report. A caller measures
    the difference across an episode to get that episode's spend, so the seam is expected
    to accumulate rather than reset.
    """
    reporter = getattr(similarity, "usage", None)
    return SimilarityUsage() if reporter is None else reporter()
