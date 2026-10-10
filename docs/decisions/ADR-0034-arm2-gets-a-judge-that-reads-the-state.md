# ADR-0034 — Fill arm 2's seam with a judge that reads the state, and register it before it is called

- **Status:** proposed
- **Date:** 2026-10-10
- **Supersedes:** nothing. It adds a fourth arm 2 scorer behind the seam ADR-0002 fixed, and
  narrows nothing already decided.
- **Deciders:** repository owner, in issue #264. This record states the resolution chosen for that
  issue so a later reader can tell whether the code complies with it.

## Context

**The question.** At matched coverage, does executable-precondition dispatch (arm 3) mis-fire less
often than a model that is shown the request **and the repository state** and asked how well each
compiled program fits it? The issue is that question, and the README's own
[What this is not](../README.md) table already answers it in the negative: every arm 2 measured so
far -- the shipped lexical overlap, #104's embedding, #256's pinned reranker -- compares text with
text. None of them can *verify* state, so "running checks beats reading text" is close to built
into the comparison. A model that reads the state as text is the strongest reasonable alternative,
and it is the baseline a reviewer will ask for.

**What it is built on, rather than around.** Issue #104 scaffolded the seam for exactly this:
`Similarity` is a one-method Protocol, `ScoresMany.score_many` answers one query against many
candidates in one call (revision 122 reproduced the committed reranker figures through that path),
`SimilarityUsage` and `ReportsUsage` meter a scorer in **its own currency**, and
`bench.cross_encoder_similarity` is a working example of a model behind the seam: pairwise
`__call__`, batched `score_many`, memoised per input, `usage()` reporting its calls. On the other
side, `bench.rescore` re-measures a finished run with no model call and no rebuild, the three
frozen libraries are committed under `results/replicates-2026-10-05/`, and `provider.py` is the
only module allowed to talk to an LLM -- with an error taxonomy that already distinguishes a
transient transport failure, an empty completion that still cost tokens, and an auth failure that
must stop a run rather than be recorded as data.

**What is new, and why it needs a decision rather than a patch.**

- **Sampling variance returns to arm 2.** The primary metric moved from episode level to
  pair level *because* an LLM's sampling variance made the earlier comparison underpowered. A
  judge is an LLM, so arm 2's number becomes stochastic while arm 3's stays deterministic.
  Revision 41 already records that temperature 0 is not determinism on a hosted model. Comparing
  the two without measuring the judge's own repeatability would read noise as mechanism.
- **The pair-level stage has no accounting for a paid scorer.** `embedding_tokens` and
  `embedding_calls` are written per **episode** by `bench/run.py`; the pair-level stage
  (`bench.live._pair_level` through `library_pair_outcomes`) records no seam usage at all, so a
  judge's spend would be invisible precisely where the issue says it must be reported.
- **A figure that cannot be recomputed is not a result.** Every other scorer is deterministic, so
  `rescore` reproduces its figures from the committed library alone. A judge cannot: the same
  prompt may answer differently tomorrow, so the *scores* have to be committed as data.

**Nothing has been called yet, and that is the point of the order.** This record and the
implementation land before the first judge call, as CONTRIBUTING rule 8 requires; the floor
(decision 7) and the three rescores need a provider key, which the caller supplies and which was
not supplied when this was written. So the registration is what exists first, and the run is what
comes after it -- logged in the spec's revision history, with the commands in the decision's own
terms.

## Decision

1. **The judge is a scorer behind the existing seam**, `bench.judge_similarity.JudgeSimilarity`,
   implementing `Similarity`, `ScoresMany` and `ReportsUsage`. Nothing in `library.py`,
   `coverage.py`, `primary.py` or `rescore.py` learns what a judge is: it is constructed and
   injected like every other arm 2, and arm 3 is untouched by construction because it does not
   read the seam.
2. **It sees exactly what arm 2 sees**: the request, the `StateFingerprint` rendered by
   `as_text()`, and the candidate program's `_program_text` (its `intent` plus its predicate
   *descriptions*). The probe strings are deliberately **not** in the prompt, because a judge that
   reads the probes is reasoning about the predicates arm 3 executes -- a different mechanism and a
   separate experiment (see the alternatives table).
3. **One provider call per (request, state) pair, in `score_many`**, returning one score per
   candidate in the order given, on the same `[0, 1]` contract as every other scorer. This keeps
   the coverage sweep meaningful (a judge that merely *names* one program degenerates the curve
   into a step) and keeps the cost at one call per pair rather than one per candidate.
   `__call__` remains available and memoised, so the probe's pairwise loop works unchanged.
4. **Model, temperature and prompt are pinned in code** and recorded per call and per cache
   record; `PROMPT_VERSION` is bumped whenever the prompt text changes, and the prompt's hash is
   part of every artifact the run writes.
5. **The scores are the evidence.** The judge writes a JSONL cache as it goes, keyed by the digest
   of `(request, state text, candidate texts)`. A cache whose prompt hash, model or per-record
   candidate count disagrees with the running configuration is **refused**, not reused, so a
   changed prompt cannot silently inherit an old score. `bench.rescore --judge-cache` recomputes a
   figure from that file with **no provider call and no tokens**, and the cache is committed under
   `results/`.
6. **Failures stay in the denominator.** An empty completion, a transport error, an unparseable
   reply and a reply whose scores are the wrong length or outside `[0, 1]` all become an **abstain**
   -- `0.0` for every candidate, which is an arm-2 non-fire and is counted as such -- and each is
   counted separately in the stage's record. `ProviderAuthError` is never recorded: it is re-raised
   and stops the run, because every later call would fail the same way and a run of failed rows
   looks measured while measuring nothing (issue #157's precedent). There are no silent retries;
   a failed call's `usage`, when the provider reports it, is counted.
7. **The floor comes first, and it is a gate.** The judge's informed-regime strict top-1 on the
   tuned seeds is measured against each frozen library through `similarity_probe.tune_baseline` and
   judged by `report.arm2_baseline_floor` (95% Wilson lower bound above chance, 1/3). Below it the
   judge is **not a usable baseline** and no "beats text similarity" sentence may be written; the
   comparison is still reported with the verdict beside it (ADR-0007).
8. **Repeatability is measured, not assumed.** A pre-registered subsample of pairs is asked
   `k >= 2` times, and the agreement between the repeats is reported beside the judge's row, with
   the statement that the three text scorers carry no such component. A judge number is read with
   that figure in view.
9. **The judge's spend is its own currency.** `SimilarityUsage` totals (tokens and provider calls)
   are recorded in the rescore's own record beside the scorer's identity, never folded into the
   LLM's `tokens_in`/`tokens_out` and never into an episode's `embedding_*`. The budget is declared
   in the registration before the run; a run that would exceed it stops and reports.
10. **Where the numbers live:** `results/judge-<date>/run-N/` holds the score cache, the rescore's
    summary and Figure 1, and a README stating the model, temperature, prompt hash, call and token
    counts, the repeatability figure and what may not be claimed.

## Consequences

**Accepted:**

- **A stochastic arm 2.** The judge's rate carries a sampling component that the lexical,
  embedding and reranker rows do not; decision 8 bounds it but cannot remove it, and a small
  repeatability subsample bounds it only where it was measured.
- **A paid scorer on a stage that had none.** The pair-level stage now needs a key and a budget;
  the cache is what makes the committed figure recomputable, and the cache is what makes a re-run
  free rather than cheap.
- **The floor is measured pairwise.** `similarity_probe.discrimination_scores` scores one candidate
  at a time, so the judge makes roughly one call per (pair, candidate) crossing there -- about 800
  per library by the probe's own arithmetic. Routing that loop through `score_all` would cut it by
  an order of magnitude but moves the **committed** reranker floor figures, which were measured
  pairwise (the batched and pairwise paths differ below 1e-6 and agree on every count). That change
  therefore needs its own revision row and is not part of this decision.
- **No measure of *why* the judge answers as it does.** The prompt asks for scores, not reasoning,
  so a surprising number is a number; a rationale field would multiply the output tokens and give
  the figure a story it cannot check.
- **One model, one prompt.** The result is about this judge, not about judges.

**Gained:** the baseline the issue asks for, built where every other arm 2 is built, measured with
the same metric and the same frozen libraries -- and, if the judge clears the floor, a comparison
that can actually falsify "running checks beats reading text".

**New obligations:** the prompt, model or temperature may not change without a new cache, a new
prompt hash and a registration revision; `tests/test_judge_similarity.py` must keep pinning the
failure paths, the cache's refusal rules and the usage accounting; and the README sentence that
says a scorer reading the state through an LLM call was not tried must be corrected in place the
moment a judge result is committed.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Give the judge the **probe strings** as well as the state | It would reason about the very predicates arm 3 executes, so the comparison would measure how well a model simulates the gate rather than whether verifying state beats reading text. It is the more interesting *next* experiment, not this one. |
| Let the judge **name one program** and score the rest zero | One number per pair, so the sweep becomes a step function and the coverage curve stops being comparable with arm 2's other rows. Kept as the fallback if per-candidate scores prove unparseable in practice. |
| **Score pairwise** (one call per candidate) | 14 candidates per pair is 14x the calls for the same answer, and `score_many` exists precisely to answer that in one call (revision 122). Pairwise stays as the `__call__` path the probe uses. |
| **Batch** `discrimination_scores` in the same change | It changes committed reranker floor figures by a recorded <1e-6 and every count is unchanged, but a committed figure that moves is a revision, not a refactor. Deferred with its own row. |
| **No cache**: re-ask the model whenever a figure is recomputed | A figure that cannot be reproduced from what is committed is not a result, and every re-measurement would cost money and could move. The cache is the artifact, the model call is how it was made. |
| Drop failures from the denominator, or retry silently | Dropping them flatters the arm that fails most; a silent retry hides spend the ledger cannot see, which `provider.py` already refuses to do. |
| A **local** judge (a model small enough to run on the CPU) | It would remove the key, the cost and the provider variance, and it would also remove the point: the strongest reasonable alternative is a strong model reading the state. A local judge is a screen, not the baseline. |
| Compare the judge to arm 3 at the judge's own coverage | Matched coverage is the pre-registered rule (ADR-0008); comparing at different coverages is the confound the rule exists to remove. |

## What would reverse this decision

- **A judge that does not clear the floor** on a library. Then it is not a usable baseline for that
  library, the comparison may not be worded as a win, and the finding is "not even a state-reading
  model makes text dispatch usable" -- reported as such, not as a null.
- **A judge whose repeats disagree more than its gap from arm 3.** Then the number is a draw from a
  distribution the run cannot pin, and the honest output is the repeatability figure with the
  comparison labelled unreadable at this k.
- **The batching decision landing** (a judged probe through `score_all`), which re-measures the
  floors and needs revision rows for the figures that move.
- **A second model landing.** Then this row is one judge and the result is about judges, not a
  category, and this ADR's scope narrows to the first one measured.
