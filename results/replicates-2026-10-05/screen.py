"""Screen pinned local text scorers on arm 2's floor (spec §7 item 11), replicates 2 and 3.

The floor is the informed regime's strict top-1 on the tune seeds, against each run's frozen
library (`bench.live.baseline_floor`); replicate 1's floor is not measurable, so it is not
screened. Each argument is `KIND:MODEL_ID`, and the model is loaded at the Hub revision printed
beside its result:

* `bi` -- a bi-encoder: `(cos + 1) / 2` of the normalised embeddings, each text encoded alone and
  cached (a batch of one, so the shape never varies).
* `ce` -- a reranker: its sentence-transformers default activation (the logistic) on the logit for
  `(request, program text)`.
* `nli` -- an NLI cross-encoder: the entailment probability of the request given the program text.

Usage, from the repository root with the `embedding` extra installed:

    python results/replicates-2026-10-05/screen.py ce:cross-encoder/ms-marco-MiniLM-L-12-v2
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

import numpy as np
from huggingface_hub import model_info
from sentence_transformers import CrossEncoder, SentenceTransformer

from precondition_library.bench.live import baseline_floor
from precondition_library.library import Library
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.similarity import Similarity

RUNS = [Path(__file__).parent / f"run-{n}" for n in (12, 13)]


def scorer(kind: str, model_id: str, revision: str) -> Similarity:
    if kind == "bi":
        encoder = SentenceTransformer(model_id, revision=revision)

        @cache
        def embed(text: str) -> np.ndarray:
            return encoder.encode([text], batch_size=1, normalize_embeddings=True)[0]

        return lambda query, candidate: (float(np.dot(embed(query), embed(candidate))) + 1) / 2
    model = CrossEncoder(model_id, revision=revision)
    if kind == "nli":
        labels = {name.lower(): int(i) for i, name in model.model.config.id2label.items()}
        entailment = labels["entailment"]

        @cache
        def entails(query: str, candidate: str) -> float:
            probs = model.predict([(candidate, query)], batch_size=1, apply_softmax=True)[0]
            return float(probs[entailment])

        return entails
    if kind != "ce":
        raise ValueError(f"unknown kind {kind!r}; choose bi, ce or nli")

    @cache
    def relevance(query: str, candidate: str) -> float:
        return float(model.predict([(query, candidate)], batch_size=1)[0])

    return relevance


def main(specs: list[str]) -> None:
    for spec in specs:
        kind, model_id = spec.split(":", 1)
        revision = model_info(model_id).sha
        assert revision is not None
        similarity = scorer(kind, model_id, revision)
        figures = []
        for run in RUNS:
            library = Library(
                run / "library-two-sided",
                similarity=similarity,
                evaluate_preconditions=evaluate_preconditions,
            )
            floor = baseline_floor(library)
            figures.append(f"{run.name} {floor.decided}/{floor.decidable} lb={floor.lower_bound}")
        print(spec, revision, *figures, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
