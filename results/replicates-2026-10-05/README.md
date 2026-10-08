# Three replicate primary-only builds, 2026-10-05

The evidence behind the README's [Primary result](../../README.md#primary-result): the three
whole-run replicates (spec §7 item 2) of `bench.live --primary-only`. Each run built its own
frozen library from the admit set (ADR-0032) and then measured the pair-level primary metric
(ADR-0022) on it, with no model call after the build. The per-run table and the discussion are on
[#214](https://github.com/Shyboy0499/precondition-library/issues/214#issuecomment-5999250801).

Committed because a frozen library is the artifact every pair-level figure is computed from
(ADR-0009), and a figure that cannot be recomputed from what is committed is not a result. With
these, anyone can re-measure the primary metric -- with the shipped arm 2 or another -- without a
model key and without rebuilding.

## What each directory holds

| file | what it is |
| --- | --- |
| `library-two-sided/` | the frozen library: every compiled program with its `history.jsonl`, admitted or refused, and `build.json` |
| `plan.json` | the run's `LivePlan` and model, as `bench.live` wrote it first |
| `build.jsonl` | one ledger row per build episode: outcome, tool calls, tokens, admission and its reason |
| `build.transcripts.jsonl` | each build episode's whole solve: the request, every command and its output |
| `summary.json`, `summary.txt` | the run's own summary: floor, Figure 1, Claim 2 |
| `primary/` | Figure 1: `figure1.csv` (every operating point with its Wilson interval), `figure1.png`, `primary.txt` |

Not committed: the positive-only libraries (the admission factorial's second library; no pair-level figure
reads them), and the sandboxes.

## Provenance

| run | replicate | code (main) | model | notes |
| --- | --- | --- | --- | --- |
| `run-11` | 1 | `a6ff042` | `deepseek-flash` | Built before #244 (awk `{next}`), #245 (`^{param}` anchors) and #246 (empty replies retried): both lockfile programs met the awk defect (one would have been refused anyway) and a third lockfile compile was lost to an empty model reply; one container restart, resumed with `--resume`; the pair-level stage was recomputed with #247's code after its Figure 1 plot crashed on a Wilson rounding error. Re-gated offline under the final admission it reads arm 3 0/187 against arm 2 141/186, floor still not measurable. |
| `run-12` | 2 | `d524978` | `deepseek-flash` | Every resolution of every intent admitted. |
| `run-13` | 3 | `44a1ffc` | `deepseek-flash` | |

## Re-measuring

```bash
# the shipped lexical arm 2: reproduces summary.txt exactly
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-12 \
  --scorer lexical --out /tmp/run-12-lexical

# the pinned embedding arm 2 (#104): needs the embedding extra and huggingface.co reachable
uv sync --extra dev --extra embedding
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-12 \
  --scorer embedding --out /tmp/run-12-embedding
```

The lexical rescore of `run-12` was checked against its own summary and matches it to the last
digit: arm 2's threshold, 149/185 at matched coverage, the 111/240 floor.

## Embedding arm 2

Each run re-measured with arm 2 swapped for the pinned embedding scorer of #104
(`sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`,
recorded in each `rescore.json`), with no model call and no rebuild:

```bash
python -m precondition_library.bench.rescore --run results/replicates-2026-10-05/run-N \
  --scorer embedding --out results/replicates-2026-10-05/run-N/rescore-embedding
```

Each `run-N/rescore-embedding/` holds that rescore's `summary.json`, `summary.txt`, `rescore.json`
and `primary/` (Figure 1). The threshold is swept to arm 3's coverage exactly as for the lexical
arm; it lands near 0.84 because the scorer maps cosine to `(cos + 1) / 2`, which puts every score in
a narrow band above 0.5.

| | run-11, lexical | run-11, embedding | run-12, lexical | run-12, embedding | run-13, lexical | run-13, embedding |
| --- | --- | --- | --- | --- | --- | --- |
| arm 2 floor: strict top-1 (Wilson lower bound vs 0.333) | not measurable | not measurable | 111/240 (0.401), usable | 112/240 (0.405), usable | 111/240 (0.401), usable | 96/240 (0.340), usable |
| arm 3: coverage, mis-fires | 187/400, 0/187 | 187/400, 0/187 | 187/400, 0/187 | 187/400, 0/187 | 189/400, 0/189 | 189/400, 0/189 |
| arm 2 at matched coverage: mis-fires | 148/187 | 143/185 | 149/185 | 168/189 | 143/187 | 169/187 |
| difference (arm 2 − arm 3) | +0.791 | +0.773 | +0.805 | +0.889 | +0.765 | +0.904 |
| smallest detectable difference (50% base rate) | 0.145 | 0.145 | 0.145 | 0.144 | 0.144 | 0.144 |
| Claim 2 | registered wording kept | kept | kept | kept | kept | kept |

Arm 3 is identical under both scorers, as it must be: it does not read the scorer.

**What it shows.** The embedding arm 2 does not narrow the gap. At matched coverage it mis-fires
on 77–90% of its fires against arm 3's 0%; the gap widened in replicates 2 and 3 (+0.08, +0.14) and
narrowed by 0.02 in replicate 1, and in every replicate it stays five to six times the smallest
detectable difference.

**What it does not show.** That a *strong* text scorer would keep the gap. On the floor this
embedding is no stronger than the lexical arm -- one more correct top-1 in replicate 2, fifteen
fewer in replicate 3, where its lower bound clears chance by 0.007 -- so this measures a different
text scorer, not a better one.

## A stronger text scorer: the screen

The embedding arm above clears the floor no better than the lexical one, so the gap it keeps
says nothing about a *strong* text scorer. To find one, thirteen pinned local models were screened
on the floor itself -- the informed regime's strict top-1 on the tune seeds against each frozen
library (`bench.live.baseline_floor`), which is what the tune seeds are for (spec §7 item 5); the
pair-level metric is measured on the disjoint pair seeds. Replicate 1 is not screened because its
floor is not measurable. Reproduce any row with [`screen.py`](screen.py); the revision is the Hub
commit each model was loaded at.

| kind | model | revision | run-12 | run-13 | together |
| --- | --- | --- | --- | --- | --- |
| bi-encoder | `sentence-transformers/all-MiniLM-L6-v2` (the embedding arm) | `1110a243` | 112/240 | 96/240 | 208/480 |
| bi-encoder | `sentence-transformers/all-mpnet-base-v2` | `e8c3b32e` | 120/240 | 112/240 | 232/480 |
| bi-encoder | `BAAI/bge-base-en-v1.5` | `a5beb1e3` | 128/240 | 112/240 | 240/480 |
| bi-encoder | `BAAI/bge-large-en-v1.5` | `d4aa6901` | 112/240 | 105/240 | 217/480 |
| bi-encoder | `mixedbread-ai/mxbai-embed-large-v1` | `b33106f5` | 121/240 | 112/240 | 233/480 |
| reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | `233902d2` | 152/240 | 113/240 | 265/480 |
| **reranker** | **`cross-encoder/ms-marco-MiniLM-L-12-v2`** | `7b023523` | **152/240** | **137/240** | **289/480** |
| reranker | `BAAI/bge-reranker-base` | `2cfc18c9` | 128/240 | 135/240 | 263/480 |
| reranker | `BAAI/bge-reranker-large` | `55611d7b` | 112/240 | 135/240 | 247/480 |
| reranker | `BAAI/bge-reranker-v2-m3` | `953dc6f6` | 128/240 | 137/240 | 265/480 |
| reranker | `mixedbread-ai/mxbai-rerank-base-v1` | `800f24c1` | 136/240 | 145/240 | 281/480 |
| reranker | `mixedbread-ai/mxbai-rerank-large-v1` | `98f65584` | 120/240 | 136/240 | 256/480 |
| NLI | `cross-encoder/nli-deberta-v3-base` | `6c749ce3` | 112/240 | 112/240 | 224/480 |

Chance is 80/240. Rerankers, which read the request and the program text together, beat every
bi-encoder, and bigger was not better. `ms-marco-MiniLM-L-12-v2` scored highest, with 95% lower
bounds of 0.571 and 0.508 against chance 0.333 -- clearly above the floor where the embedding arm
was at 0.405 and 0.340. It ships as `bench.cross_encoder_similarity.CrossEncoderSimilarity`, and
`bench.rescore --scorer cross-encoder` re-measures a run with it. The rescores of the three runs
with it are reported in a section to follow.
