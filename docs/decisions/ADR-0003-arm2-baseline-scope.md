# ADR-0003 — Quote arm 2's baseline per intent over the whole ambiguous subset, and keep the lexical seam

- **Status:** proposed
- **Date:** 2026-09-18
- **Supersedes:** nothing (corrects the measurement recorded in spec revisions 31 and 32)
- **Deciders:** repository owner

## Context

ADR-0002 chose deterministic lexical similarity for arm 2 behind a `Similarity` seam, and named an
embedding model as the intended replacement. Issue #104 then built a discrimination probe to ask
whether a scorer can tell which resolution a state needs from the text alone — the question that has
to be answered before the seam is swapped. #116 found that probe measuring the wrong text: it scored
each request against a resolution's `rationale` rather than `_program_text`, the artifact a
dispatcher compares against. That was fixed in #118.

Correcting the text exposed a second problem, in the corrected figure itself. **Revisions 31 and 32
report the shipped scorer at AUC 0.4778 and "9 of 24", which is `sync_fork_with_upstream` alone,
quoted as the family's.** Revision 30, which introduced the probe, framed it over both ambiguous
intents — 56 pairs and 168 crossings. The withdrawal in revision 31 narrowed the measurement to one
intent and did not say so, and the conclusion drawn there ("at or below chance, so the case for an
embedding model is stronger") was built on that narrowing.

Measured over the whole ambiguous subset, on the committed gold programs, with the shipped
`lexical_similarity` scoring `_program_text` against the request:

| intents | pairs | crossings | AUC | strict top-1 | chance |
| --- | --- | --- | --- | --- | --- |
| `restore_submodule_state` | 28 | 84 | **0.7264** | 14/24 (58%) | 33% |
| `sync_fork_with_upstream` | 28 | 84 | **0.4778** | 9/24 (38%) | 33% |
| both (the ambiguous subset) | 56 | 168 | **0.5722** | 23/48 (48%) | 33% |

A constant scorer that cannot discriminate gives AUC 0.5000 and top-1 0/48 on the same crossings.

So the pooled baseline is **above chance, not below it**, and the two intents differ by 0.25 AUC and
20 points of top-1. Neither intent's number describes the family, and the pooled number describes
neither of them. Reproduce the table with
`pytest tests/test_similarity_probe.py -q -s -k pooled_baseline`.

The replacements #116 left open were also measured, over the same pairs and crossings
(`-k weighting_alternatives`):

| scorer on the shipped artifact text | AUC | strict top-1 |
| --- | --- | --- |
| lexical Jaccard (shipped) | 0.5722 | 23/48 |
| IDF-weighted Jaccard | 0.5825 | 19/48 |
| IDF-weighted cosine | 0.5910 | 15/48 |

IDF weighting raises the AUC and **lowers** the number dispatch actually acts on. Dropping the
constant `intent` from `_program_text` — the other candidate — moves the AUC by 0.0104 and leaves
top-1 at 23/48. Separately, IDF needs a corpus to compute document frequencies from, and arm 2's
seam is a two-argument `(query, candidate) -> float` with nowhere to put one: adopting it would mean
widening the seam that ADR-0002 deliberately kept to one method.

Two supporting measurements. Of the 48 decidable pairs, **none** has the correct resolution tied at
the top — every pair's three candidates score at three distinct levels — so the misses are genuine
mis-orderings rather than ties a better tie-break could recover. And the probe's crossing functions
take one `variant -> text` mapping with no intent attached; variant ids are unique only *within* an
intent, so handing them pairs from two intents returns a plausible wrong number (AUC 0.6980, top-1
18/48) instead of failing. They now refuse.

## Decision

1. **Arm 2's baseline is quoted over the whole ambiguous subset with the per-intent breakdown**, as
   in the table above. A single intent's figure may be reported only when it is named as that
   intent's. Spec revision 33 records the correction to revisions 31 and 32.
2. **Arm 2 stays lexical behind the `Similarity` seam.** No IDF or BM25 weighting, and no change to
   `_program_text`'s candidate text, because neither alternative improves strict top-1 — the metric
   dispatch acts on — and IDF cannot be expressed in the seam without widening it.
3. **Strict top-1 is the operative number, with the AUC reported beside it.** The denominator is the
   pairs that have a correct resolution; the negative pairs stay in `pairs` and out of `decidable`.
   Where the two disagree, top-1 governs, because dispatch takes the argmax.
4. **Where the two intents disagree, the disagreement is a result, not noise to be pooled away.**
   Anything the claim says about arm 2's strength relative to arm 3 is reported per intent.
5. **The embedding swap stays open, and is the only remaining candidate.** Filling the seam is a
   change of mechanism, not of weighting, so it is decided separately and against this baseline,
   with a model that can be pinned per episode and its cost recorded (ADR-0002's obligation).

## Consequences

**Accepted:** keeping lexical means the primary comparison's fairness varies by intent. On
`sync_fork_with_upstream` arm 2 scores at chance, so a win for precondition dispatch there says less
than the same win would against a competent text baseline. That cuts toward the claim being *too
easy* on that intent, which is the direction that damages it, and it is the reason decision 4
forbids hiding it in a pooled figure. Pooling also mixes two difficulties; the pooled AUC of 0.5722
sits above one intent and below the other.

**Gained:** the baseline is now a measured, reproducible number over the subset the metric is
defined on, instead of one intent's figure generalised to the family. Two candidate fixes are
rejected with numbers rather than left as open speculation, which is what the #116 question needed.

**New obligations:** the probe's candidate source must stay `_program_text`; a third ambiguous intent
must be added to the comparison with its own candidates and its own row; and any future claim about
arm 2's strength carries the per-intent breakdown.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Keep quoting the withdrawn 0.4778 / 9-of-24 as the baseline | It is one intent's figure, and the two intents differ by 0.25 AUC. The reversal recorded in revision 31 rests on it. |
| Pool both intents into one headline number and stop there | 0.5722 is above one intent's AUC and below the other's; it describes neither. Kept as a summary, with the breakdown required beside it. |
| IDF-weighted Jaccard or cosine | Raises the AUC, lowers strict top-1 (19/48 and 15/48 against 23/48). And it needs a corpus, which the one-method seam has nowhere to carry. |
| Drop the constant `intent` from `_program_text` | +0.0104 AUC, top-1 unchanged at 23/48. It would invalidate comparability with the figures already recorded, for no measured gain. |
| Score the resolution's `rationale` as the candidate text | Retracted in #116 and revision 31: it is not what a dispatcher compares, and it flatters the scorer by ~0.2 AUC. |
| Gate the probe's figure as a regression threshold | Rule 1: it is an exploratory figure, and a threshold would turn it into a claim. It is reported, never gated. |
| Fill the embedding seam now | #104's actual decision, and a change of mechanism rather than of weighting. No model is available in this environment and the per-episode pinning ADR-0002 requires is not in place. |

## What would reverse this decision

A scorer behind the seam — an embedding model, or a weighting that the seam can carry — that
materially raises strict top-1 on the ambiguous subset as measured by this probe and the per-intent
tests. That would make the lexical implementation a handicap rather than a proxy, and the
comparison would have to be re-run with the embedding arm rather than reported against lexical. A
third ambiguous intent whose figures invert the pooled ordering would also require re-deciding what
the pooled number is for.
