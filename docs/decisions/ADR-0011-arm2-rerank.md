# ADR-0011 — Give arm 2 an optional top-k rerank through a second `Similarity` seam, thresholded on the reranker's score

- **Status:** accepted (2026-09-30, as written)
- **Date:** 2026-09-30
- **Supersedes:** nothing (implements issue #4's "top-k rerank before selection"; ADR-0002's lexical default stands)
- **Deciders:** repository owner

## Context

Issue #4 asks that arm 2's representation be "intent + canonicalised StateFingerprint
text, with top-k rerank before selection". The first half already existed:
`library._query_text` sends the request plus the fingerprint rendered as words. The
rerank did not. `Library.match_semantic` scored every admitted program with one
`Similarity`, thresholded that score, and took the top.

A rerank makes arm 2 a stronger baseline, which is the point. An untuned or single-stage
control arm invites the reviewer's "straw man" objection that #4 and spec §7 item 5 exist
to pre-empt. But the reranker can be several things, and they differ in what they cost:

- another `Similarity` (for example the pinned embedding model from #104 over a lexical
  first stage), which spends in its own metered currency and never calls the LLM;
- an LLM choosing among the top k, which is the strongest option but makes every arm-2
  dispatch cost LLM calls, so arm 2's replays would no longer be free while arm 3's
  stay free. That changes Claim 1's cost comparison;
- a cross-encoder, which is more precise than a bi-encoder but adds another model
  dependency and download.

The owner chose the first: a second scorer seam.

Two further choices follow from it. The first is which score the threshold judges once
there are two. The second is where the rerank lives. `agents/dispatch.py` forbids a
re-rank there, because logic one arm gets and the other does not is §4's confound.

## Decision

1. **`Library(reranker=..., rerank_k=3)`.** `reranker` is any `Similarity`, and `None`
   keeps arm 2 single-stage, unchanged. The first-stage `similarity` retrieves the top
   `rerank_k` admitted programs (ties by id), and the reranker rescores them.
2. **The reranker's score decides.** With a reranker, its score is the one the
   threshold judges, the one `match_semantic` orders by, and the one `dispatch_score`
   records. The first stage only retrieves. So the threshold is tuned on the score the
   dispatch actually acts on, and it is recorded next to `rerank_k`.
3. **`rerank_k` defaults to 3.** Both measurable intents declare three resolutions, so
   the reranker sees every resolution a request could need. 3 was also
   `match_semantic`'s existing `limit`. A value below 1 is refused.
4. **The rerank lives in `Library.match_semantic`**, behind the matcher. It does not live
   in `dispatch.py`, which still makes one call and reports its verdict.
5. **It is metered like the embedding seam.** The reranker's reported usage is added to
   the row's `embedding_tokens` and `embedding_calls`, never to the LLM fields. A scorer
   used as both stages is counted once.
6. **Rows record `rerank_k`**: the library's value when a reranker ran, `None` otherwise.
7. **The pair-level adapter matches the library.** `bench.coverage.arm2_outcomes` takes
   the same `reranker` and `rerank_k`, so the mismatch-vs-coverage analysis measures the
   arm the episodes run.

## Consequences

**Accepted:**
- No reranker is chosen here. The seam ships with lexical as the default single stage.
  Whether the eval runs with the embedding model as reranker is a configuration decision
  for the tune pass, and it must be recorded (`rerank_k` and `embedding_tokens` on the
  rows say whether one ran).
- A threshold tuned without a reranker does not transfer to a run with one, because the
  thresholded score changes. The tune pass has to tune the configuration it will run.
- Arm 2 now has more knobs than arm 3. That is deliberate: arm 2 is the control, and
  giving it every fair advantage is what makes a win over it mean something.

**Gained:** arm 2 can be run as a retrieve-then-rerank pipeline, the standard shape for
a strong text-similarity baseline, without an LLM call and without touching
`dispatch.py`.

**New obligations:** the eval report states whether arm 2 ran with a reranker and which
one, and ADR-0007's floor is measured on that same configuration.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| LLM reranker | Makes arm 2's dispatch cost LLM calls while arm 3's stays free, which breaks the cost comparison's symmetry (owner's choice). |
| Cross-encoder | Another model dependency and download, for precision the seam can reach later by accepting a cross-encoder as a `Similarity`. |
| Threshold on the first-stage score | The first stage would gate coverage while the reranker decides, so the swept score would not be the deciding one, and the sweep would stop measuring the arm's decision. |
| Rerank in `dispatch.py` | Forbidden there: logic one arm gets and the other does not, outside the matcher (§4). |

## What would reverse this decision

- Evidence on the tune set that the reranker lowers arm 2's strict top-1 against the
  first stage alone. The eval would then run single-stage, which is a configuration
  change, not a reversal of the seam.
- A decision to spend LLM calls on arm 2's dispatch after all. That changes Claim 1's
  cost comparison and needs its own ADR.
