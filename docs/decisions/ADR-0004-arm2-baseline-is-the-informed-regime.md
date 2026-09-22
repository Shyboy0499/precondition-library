# ADR-0004 — Quote arm 2's baseline on the informed request regime, and stop pooling it with the uninformed tripwire

- **Status:** accepted (2026-09-20, as written)
- **Date:** 2026-09-21
- **Supersedes:** nothing (narrows the baseline scope of ADR-0003, which stays accepted as a record)
- **Deciders:** repository owner

## Context

ADR-0003 accepted arm 2's baseline as the probe's figure over the whole ambiguous subset, pooled
over both request regimes (AUC 0.5722, strict top-1 23/48; re-measured 0.5340 and 23/48 in spec
revision 35 after the gold descriptions were rewritten). Pooling the regimes is a defect.
`LabelledPair.informed` records which channel a request's text arrived through, and
`bench/textcontrol.py` states the consequence: the uninformed sampler never consults state, so
every positive has a negative with an identical score and the AUC is **0.500 for any classifier and
any phrasing list**, including a deliberately leaky one. That is a property of the construction, not
a measurement. The informed channel is the opposite boundary: its wording nearly gives the
resolution away, so a high score there is expected and is the genuine measurement of how far the
text alone gets a dispatcher. A number that averages the two describes neither.

Re-measured from the committed code on the hand-written gold programs and the probe's seeds 0–3 --
which are **not** the pre-registered split, and are exploratory figures that are reported, never
gated:

| regime | scorer | pairs | decidable | AUC | strict top-1 | chance |
| --- | --- | --- | --- | --- | --- | --- |
| informed | lexical (shipped) | 24 | 24 | **0.6172** | **15/24 (63%)** | 33% |
| informed | embedding (pinned) | 24 | 24 | 0.5859 | 12/24 (50%) | 33% |
| uninformed | lexical (shipped) | 32 | 24 | **0.5000** | 8/24 (33%) | 33% |
| uninformed | embedding (pinned) | 32 | 24 | 0.5000 | 8/24 (33%) | 33% |

Per intent on the informed regime, lexical is `restore_submodule_state` **0.8125 and 8-of-12**
against `sync_fork_with_upstream` **0.6007 and 7-of-12**; embedding is 0.6389 and 8-of-12 against
0.5729 and 4-of-12. The uninformed regime holds all **8 negative pairs** (4 per intent) — pairs
where no resolution is correct — and the informed regime holds none, because informed wording
exists only where a resolution does. Reproduce with
`pytest tests/test_similarity_probe.py -s -k informed_baseline` and
`pytest tests/test_embedding_similarity.py -s -k measured_against_lexical`.

Two readings follow, and both cut against the claim. First, the corrected baseline is **stronger**
than the one ADR-0003 recorded: **63%, not 48%**. A stronger baseline makes Claim 2 harder to
support, because a win for precondition dispatch now has to be won against a text scorer that is
competent on the informed channel rather than one that is barely above chance. Second, the earlier
reading that the shipped scorer is "at chance" on `sync_fork_with_upstream` was an artefact of
pooling: on the informed channel it scores 0.6007 and 7-of-12 (58%) there, and the uninformed
channel is chance by construction. The conclusion drawn from the pooled figure in issue #116 — that
the case for an embedding behind the seam is stronger — does not follow from the informed baseline,
and the embedding measures *below* the lexical proxy on the informed top-1 (12/24 against 15/24).

The evidence is weak in the way every probe figure here is weak: it is a proxy measurement on
hand-written gold, not a compiled library, on an exploratory seed set, and it is reported rather
than gated. It is strong enough to fix what the probe reports, because the pooling defect is
structural and independent of the sample.

## Decision

1. **Arm 2's baseline is quoted on the informed request regime**, per intent and over the whole
   ambiguous subset, with strict top-1 operative and the AUC beside it. The informed figure is
   **AUC 0.6172 and strict top-1 15/24 (63%)**; the per-intent breakdown is 0.8125 / 8-of-12 and
   0.6007 / 7-of-12.
2. **The uninformed regime is reported beside the baseline as a plumbing tripwire, never as
   baseline material.** It is chance by construction, and a departure from 0.500 means state has
   begun reaching the sampler — the regression that would restore the original flaw. The negative
   pairs belong to it.
3. **The two regimes are never pooled.** The probe's single-mapping functions take a required
   `regime`, `compare_scorers` returns one row per (regime, scorer) with the informed row first, and
   there is no pooled mode. A pooled figure is not a result this experiment can quote.
4. **ADR-0003 is narrowed, not rewritten.** Its decisions 2 (stay lexical behind the `Similarity`
   seam), 3 (strict top-1 is the operative number), and 5 (the embedding swap is decided separately,
   against this baseline) stand. Its decision 1 — "over the whole ambiguous subset with the
   per-intent breakdown" — is narrowed to the informed regime of that subset. ADR-0003 stays
   accepted and keeps its pooled figures as the record of what was measured then.
5. **The corrected baseline is acknowledged as stronger, and the claim is quoted against it.**
   Wherever arm 2's baseline appears in a live document, it is the informed figure with its
   per-intent breakdown, and the ADR-0003 pooled numbers are attributed to the record rather than
   restated as current.
6. **The embedding swap stays closed for now.** On the informed regime the pinned embedding does not
   improve on lexical strict top-1 (12/24 against 15/24), so decision 5 of ADR-0003 has no measured
   trigger yet.

## Consequences

**Accepted:** the project's published arm-2 baseline rises from 48% to 63%, and that is a cost
rather than a win — it makes the central claim harder to support and withdraws the reading that the
lexical proxy was too weak to be a fair comparison. The informed channel is also the boundary
condition where the wording nearly gives the answer away, so its figure is partly a property of the
request channel; the channel that would be the fairer test of the mechanism, the uninformed one, is
unmeasurable by construction. Choosing the measurable regime over the fair one is the honest reading
of the construction, and it is recorded here rather than hidden.

**Gained:** the baseline describes one regime instead of an incoherent average; the tripwire regains
the role `bench/textcontrol.py` gave it; the probe refuses the defect structurally, so a future
caller cannot reintroduce it by taking a default; and the conclusion drawn in #116 from a pooled
figure is corrected rather than left standing.

**New obligations:** every live document quoting arm 2's baseline quotes the informed figure with
the per-intent breakdown and labels the uninformed figure a tripwire; records (ADR-0003, spec
revisions 31–35) keep their pooled numbers and are not edited; a third ambiguous intent is added to
the informed comparison with its own row; and any re-measurement after the gold descriptions or the
grid move repeats the regime split rather than a single number.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Keep the pooled figure as the headline and report both regimes beside it | The pooled number averages a channel where the text is the answer in disguise with one that is chance by construction; a headline that is the mean of 63% and chance is not a baseline for anything. |
| Quote the uninformed regime as the baseline | It is 0.500 for any classifier by construction, so it measures the sampler and not arm 2. It is the tripwire, and moving it into the baseline would swap a real defect for a vacuous number. |
| Keep the pooled figure but document it as a "summary" | A summary is still what a reader quotes. The structural fix is a required `regime` with no pooled mode; a documented default is the bug that produced this ADR. |
| Make `regime` optional and default to the informed regime | Better than the pooled default, but a caller measuring the uninformed channel would silently get the informed one; an explicit argument is cheap and makes the filter visible at every call site. |
| Edit ADR-0003's figures in place | CONTRIBUTING rule 5: records of a time are not rewritten. Once the pooled figures are replaced, a reader can no longer see that the earlier baseline was chosen or that the correction happened. A narrowing ADR is the mechanism, and it is why ADR-0003 stays accepted. |
| Drop the uninformed regime from the probe entirely | It is the regression guard for the original flaw — state reaching the sampler — and the negative pairs live there. Removing it would delete the tripwire to make the table tidier. |
| Re-run the embedding and quote it as the new baseline now | The embedding does not improve strict top-1 on the informed regime (12/24 against 15/24), so there is no measured reason to swap the seam; ADR-0002's obligation to decide the swap separately still holds. |

## What would reverse this decision

- A declared channel that lets the uninformed sampler carry signal about the state, making the
  uninformed regime measurable. It would then no longer be the uninformed regime, and the baseline
  question would be re-opened rather than answered here.
- A scorer behind the seam — an embedding or a weighting the seam can carry — that materially
  raises strict top-1 on the **informed** regime, which would make lexical a handicap rather than a
  proxy and force the comparison to be re-run with that scorer.
- A third ambiguous intent whose informed figures invert the per-intent ordering, which would
  require re-deciding what the pooled-over-intents informed number is for (the condition ADR-0003
  already anticipated).
- Evidence that the informed channel is so leaky that its figure is uninformative about arm 2 at
  all. That would require a different measurement of the claim; it would not make pooling the two
  regimes correct.
