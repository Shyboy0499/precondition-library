"""Arm 2's `Similarity` seam, filled with a **pinned local cross-encoder** (issue #104).

`bench.embedding_similarity` filled the seam with a bi-encoder and found it no stronger than the
lexical proxy on arm 2's own floor (spec §7 item 11): the request and each candidate are embedded
separately, so a request like "my edits are in files upstream did not touch" never meets the
predicate that reads it. A cross-encoder reads the two texts **together**, which is what a
reranker is trained for: given a query and a passage, how relevant is the passage. That is arm
2's question exactly -- given the request, how well does this program's text answer it -- so this
module is the stronger text scorer the replicate README's caveat asked for.

How it was chosen. Thirteen pinned local models were screened on the floor itself (the informed
regime's strict top-1 on the tune seeds, against replicates 2 and 3's frozen libraries; the
table is in `results/replicates-2026-10-05/README.md`, "A stronger text scorer"). Selecting on
the tune seeds is what they are for (spec §7 item 5); the pair-level metric is measured on the
disjoint pair seeds. This
model had the highest strict top-1 of any screened model, 289/480 against MiniLM's 208/480, and
it is small enough to rescore a run in minutes on a CPU.

The properties the seam needs, and how they are obtained here:

* **A score on the contract.** The reranker emits one relevance logit; the logistic function
  takes it onto `(0, 1)`, strictly increasing, so the ranking -- which is all strict top-1 and
  the AUC read -- is the model's own. The activation is passed explicitly rather than read from
  the model's config, so a revision that stored another default cannot change the scale. The
  score is **not symmetric**: the query is the request and the candidate is the program text,
  which is the order `Similarity` is called in and the order the reranker was trained on.
* **Deterministic.** A model call's batch is fixed by its own inputs, so its tensor shape cannot
  depend on what was scored before (the batch-shape reason in `bench.embedding_similarity`):
  `__call__` scores exactly one pair, and `score_many` -- what arm 2's `match_semantic` uses --
  scores one request against the library's admitted programs, in the library's order, as one
  batch. That batch is what makes a pair-level rescore minutes rather than hours. Each is
  memoised on its own inputs; a memoised score is the same float the model gave, so the cache
  changes the cost and nothing else.
* **Honest usage.** Local, so zero provider tokens; `calls` counts the model calls made, which
  the memo keeps below the number of scores asked for.
* **Pinned and lazy.** `MODEL_ID` and `MODEL_REVISION` are passed to the loader, and
  `sentence-transformers` is imported only when an instance is built (the `embedding` extra).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from ..similarity import SimilarityUsage

MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-12-v2"
"""The pinned reranker: MS MARCO passage ranking, 12 layers, English."""

MODEL_REVISION = "7b0235231ca2674cb8ca8f022859a6eba2b1c968"
"""The exact Hub commit the screen and the rescores were measured on."""


def _load_model(model_id: str, revision: str) -> Any:
    """Load `CrossEncoder(model_id, revision=revision)` with an identity activation.

    The import is inside the function for the reason `embedding_similarity._load_model` gives.
    The identity activation makes `predict` return the raw logit, so `logistic` below is the one
    place the scale is decided.
    """
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_id, revision=revision, activation_fn=_identity)


def _identity(logits: Any) -> Any:
    """The activation `predict` applies: none, so the raw logit comes back."""
    return logits


def logistic(logit: float) -> float:
    """`1 / (1 + e^-logit)`, computed without overflow at either end."""
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp = math.exp(logit)
    return exp / (1.0 + exp)


class CrossEncoderSimilarity:
    """A pinned local reranker behind the `Similarity` and `ReportsUsage` Protocols."""

    def __init__(self, model_id: str = MODEL_ID, revision: str = MODEL_REVISION) -> None:
        self._model_id = model_id
        self._revision = revision
        self._model = _load_model(model_id, revision)
        self._scores: dict[tuple[str, str], float] = {}
        self._batches: dict[tuple[str, tuple[str, ...]], list[float]] = {}
        self._calls = 0

    @property
    def model_id(self) -> str:
        """The model this instance loaded."""
        return self._model_id

    @property
    def revision(self) -> str:
        """The pinned Hub revision this instance loaded."""
        return self._revision

    def __call__(self, query: str, candidate: str) -> float:
        """How relevant `candidate` is to `query`, in `(0, 1)`: one pair per model call."""
        key = (query, candidate)
        if key not in self._scores:
            self._calls += 1
            (logit,) = self._model.predict(
                [key], batch_size=1, show_progress_bar=False, convert_to_numpy=True
            )
            self._scores[key] = logistic(float(logit))
        return self._scores[key]

    def score_many(self, query: str, candidates: Sequence[str]) -> list[float]:
        """`query` against every candidate in **one** model call: arm 2's per-pair batch.

        Deterministic for a given `(query, candidates)`, because the batch -- its members, their
        order and so its padded shape -- is the same every time; memoised on exactly that. A
        batched score is not bit-identical to the pairwise `__call__` (padding reaches other
        kernels), so the two are cached apart and never mixed: which one a figure used depends
        on the call site, never on what was scored before.
        """
        if not candidates:
            return []
        key = (query, tuple(candidates))
        if key not in self._batches:
            self._calls += 1
            logits = self._model.predict(
                [(query, candidate) for candidate in candidates],
                batch_size=len(candidates),
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            self._batches[key] = [logistic(float(logit)) for logit in logits]
        return list(self._batches[key])

    def usage(self) -> SimilarityUsage:
        """`tokens=0` because the model is local; `calls` the model calls made so far."""
        return SimilarityUsage(tokens=0, calls=self._calls)
