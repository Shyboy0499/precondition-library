"""Arm 2's `Similarity` seam, filled with a **pinned local** embedding model (issue #104).

`similarity.py` declares the seam and ships a lexical proxy. This module is the alternative
ADR-0002 named as the intended replacement: the same two-argument callable, satisfied by a
sentence-transformer instead of token overlap. It is **not** the default. ADR-0003 decision 5
keeps the shipped implementation lexical, and swapping it is a separate decision that has to be
made against a measured strict top-1 -- which the probe test in `tests/test_embedding_similarity.py`
reports.

Three properties the seam needs, and how they are obtained here.

**The score stays on the contract.** `Similarity` promises a score in `[0, 1]` where 1 is
identical, so a threshold means the same thing across implementations. Cosine similarity is in
`[-1, 1]`, so it is mapped by the affine `(cosine + 1) / 2` before it leaves `__call__`. The choice
is deliberate and its consequences are real:

- It is strictly increasing, so it preserves the ordering cosine gives. Rank-based readings -- the
  probe's AUC and its argmax top-1 -- are therefore unaffected by the mapping; only the number on a
  threshold moves. That matters because a threshold tuned on the lexical implementation does not
  transfer: lexical 0.0 is "no shared token", embedding 0.5 is "no shared direction", and they are
  not the same idea. ADR-0002 decision 5 already requires the threshold to be tuned per
  configuration, which is the honest reading of this.
- Unrelated texts land above 0.5, not near 0.0, because cosine centres on 0 and this model scores
  even unrelated short English texts with a positive cosine. Measured by
  `test_every_score_stays_in_the_unit_interval` on the probe's `sync_fork_with_upstream` requests
  against both intents' gold artifact texts: every score fell in `[0.5417, 0.8609]`, so the used
  band is narrow and the nominal midpoint separates nothing on this corpus. A caller reading a raw
  score as "fraction of overlap" would misread it, and a threshold has to be tuned inside that band
  rather than assumed at 0.5; the docstring is where that is said rather than left for a plot to
  reveal.
- Clipping negative cosine to 0.0 was the alternative. It also keeps `1.0 == identical`, but it
  collapses antiparallel and orthogonal pairs to one value, discarding the ordering information the
  AUC is built from and creating ties where strict top-1 counts a tie as no decision. The affine map
  keeps the whole range and is strictly monotone, so it introduces no ties the cosine did not have.

**It is deterministic, because the batch shape is fixed.** ADR-0002 requires anything behind this
seam to be reproducible. The model is deterministic in evaluation mode, but *only per tensor
shape*: measured on this machine with this model, two runs of the same batch shape are bit-exact
(max abs difference 0.0), while a batch of 2 against a batch of 1 differs by 8.2e-08
(`8.195638656616211e-08`) because different shapes reach different BLAS kernels. So every call
encodes exactly `[query, candidate]` as one batch of two, and nothing else. The score for a pair
cannot depend on which other pairs were scored before it, or in what order, and repeated runs are
bit-exact -- which the test asserts with `==`, not a tolerance.

**It reports its own spend honestly.** `ReportsUsage` exists so arm 2's cost cannot hide. This
model runs locally, so it bills **zero provider tokens**: `tokens=0` is the measured truth, not a
placeholder, and a non-zero value here would mean a *hosted* embedding API is behind the seam and
its tokens are a second bill that must never be added to the LLM's. `calls` is the number of encode
calls this instance made, which is the provider traffic reading `SimilarityUsage.calls` settles on:
one call per scored pair here, because one pair is one batch.

**The model is pinned and loaded lazily.** `MODEL_ID` and `MODEL_REVISION` are module constants and
the revision is passed to the loader, so the artifact is the same bytes on every machine and an
episode can record it (ADR-0002's obligation). Importing this module does **not** import
`sentence-transformers`: the import is inside `_load_model`, and `pyproject.toml` carries the
package in the separate `embedding` extra so the core install stays lean. A `mypy` override for
`sentence_transformers` keeps `mypy src` green where the package is absent (CI installs only the
dev extra); the override is the same shape as the existing `yaml` one and exists for the same
reason -- the type gap is recorded rather than silenced by adding a dependency.

The model is loaded **once per instance**, in `__init__`. A per-score load would make the probe
reload 103 weight tensors per crossing.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from ..similarity import SimilarityUsage

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
"""The pinned model. Small, English, and fast enough that the probe is a test rather than a run."""

MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
"""The exact Hub commit the measurements were taken on, passed as `revision=` to the loader.

A model id alone is not a pin: the Hub serves whatever the branch points at today, so a number
recorded against "all-MiniLM-L6-v2" would not be reproducible tomorrow. Verified after loading on
this machine: `model[0].auto_model.config._commit_hash` equals this string.
"""


def _load_model(model_id: str, revision: str) -> Any:
    """Load `SentenceTransformer(model_id, revision=revision)`, importing the extra lazily.

    The import is deliberately inside the function. It keeps `import
    precondition_library.bench.embedding_similarity` free of a multi-second torch import, and it is
    what lets CI, which installs only the dev extra, import this module at all. `Any` is the return
    type because the package may be absent (where the `mypy` override makes the name `Any` anyway);
    the value is only ever handed back to `SentenceTransformer.encode`.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id, revision=revision)


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    """Cosine similarity of two vectors, `0.0` when either has no direction.

    Computed here rather than by `normalize_embeddings=True` plus a dot product, so the definition
    is visible and the degenerate case has an answer. A zero vector -- no direction -- carries no
    evidence of similarity, which is the same answer `lexical_similarity` gives for two empty
    texts, so it maps to `0.0` rather than to the `0.5` an undefined cosine would fall through to.
    """
    dot = sum(float(left) * float(right) for left, right in zip(first, second, strict=True))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in first))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in second))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def cosine_to_unit(cosine: float) -> float:
    """The contract mapping: `(cosine + 1) / 2`, taking `[-1, 1]` onto `[0, 1]`.

    Exposed rather than inlined because it is the seam's one arithmetic decision and a reader
    checking it is the inverse of `2 * score - 1` should find it in one place.
    """
    return (cosine + 1.0) / 2.0


class EmbeddingSimilarity:
    """A pinned local sentence-transformer behind the `Similarity` and `ReportsUsage` Protocols.

    Constructing this loads the model, which needs the `embedding` extra installed and the pinned
    revision in the local HuggingFace cache. `tests/test_embedding_similarity.py` is the one caller
    today; it skips when either is absent, because CI has neither.
    """

    def __init__(self, model_id: str = MODEL_ID, revision: str = MODEL_REVISION) -> None:
        self._model_id = model_id
        self._revision = revision
        self._model = _load_model(model_id, revision)
        self._encode_calls = 0

    @property
    def model_id(self) -> str:
        """The model this instance loaded, so an episode can record what produced its scores."""
        return self._model_id

    @property
    def revision(self) -> str:
        """The pinned Hub revision this instance loaded."""
        return self._revision

    def __call__(self, query: str, candidate: str) -> float:
        """Cosine similarity of the two embeddings, mapped onto `[0, 1]` with 1 for identical.

        Exactly one encode call, over exactly `[query, candidate]`, for the determinism reason in
        the module docstring: the batch shape cannot vary with call order, so the same pair scores
        the same float every time.
        """
        vectors = self._encode([query, candidate])
        return cosine_to_unit(_cosine(vectors[0], vectors[1]))

    def _encode(self, texts: list[str]) -> Any:
        """Encode one fixed-size batch, counting the call against this instance's provider traffic.

        `batch_size=2` restates the shape invariant at the call site rather than relying on the
        library's default staying above two. The count is incremented before the call, so a failed
        encode is still reported: the work was attempted and the ledger should not silently
        under-count it.
        """
        self._encode_calls += 1
        return self._model.encode(
            texts,
            batch_size=2,
            normalize_embeddings=False,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    def usage(self) -> SimilarityUsage:
        """`tokens=0` because the model is local; `calls` the encode calls made so far.

        Zero tokens is a measurement, not a stub: this implementation talks to a local
        sentence-transformer and no provider, so it spends none of the currency the ledger's
        `tokens_in`/`tokens_out` are denominated in. A non-zero `tokens` would mean a hosted
        embedding API behind the seam, whose bill must stay in the separate `embedding_tokens`
        column and never be folded into the LLM's (issue #104).
        """
        return SimilarityUsage(tokens=0, calls=self._encode_calls)
