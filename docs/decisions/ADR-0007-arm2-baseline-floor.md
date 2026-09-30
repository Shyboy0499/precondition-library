# ADR-0007 — Require arm 2 to clear chance by its Wilson lower bound before it counts as the baseline

- **Status:** accepted (2026-09-30, as written)
- **Date:** 2026-09-30
- **Supersedes:** nothing (adds spec §7 item 11; ADR-0003 and ADR-0004 stand)
- **Deciders:** repository owner

## Context

Issue #116's last open item: *"A recorded floor. Decide, before the eval, the top-1 (or AUC)
below which arm 2 is not a usable baseline for the comparison, so that 'preconditions beat
text similarity' cannot be read off a broken baseline."* The rest of #116 is settled.
Its headline claim was a pooling artifact (ADR-0004). The candidate-text defects were fixed
(#118, #124). The lexical seam and its per-intent quoting were decided in ADR-0003. But no
floor exists anywhere in the spec or the ADRs.

Why a floor is needed: Claim 2 is a comparison **against** arm 2. If arm 2 dispatches at
chance, arm 3 "winning" says nothing about text similarity. #116 was filed because the
repository briefly believed that was the case. A floor chosen after the eval could be set
to whatever the observed baseline happened to clear, so it has to be registered now, as
§7 item 10's margin was.

**What exists to measure it with.** `bench.similarity_probe` computes strict top-1 per
regime, pooled per intent. Strict means a tie counts as no decision. Its own figures are
exploratory, on hand-written gold and probe seeds 0–3, and its docstring says they are never
gated, for a reason this ADR keeps: a threshold on a proxy figure turns an exploration into
a claim. The floor therefore needs its own measurement, on the tune seeds (spec §7 item 5,
where arm 2 is tuned) and against the library the eval will dispatch with.

**Figures for context, none of them the gate** (lexical scorer, informed regime):

| source | strict top-1 | 95% Wilson lower bound |
| --- | ---: | ---: |
| hand-written gold, probe seeds 0–3 | 15/24 (63%) | 0.427 |
| hand-written gold, tune seeds | 55/96 (57%) | 0.473 |

Chance for three candidates is 1/3. At 24 decidable pairs, a point estimate one pair above
chance (9/24) has a lower bound of about 0.21. That is why the floor judges the lower bound,
not the point estimate.

## Decision

1. **The floor.** Arm 2 is a usable baseline only if the **95% Wilson lower bound** of its
   strict top-1 exceeds chance, `1 / candidates`. Candidates are 3 for both measurable
   intents. `bench.report.arm2_baseline_floor` returns the verdict with its counts and bound.
2. **What it is measured on.** Informed regime (the baseline, per ADR-0004), `TUNE_SEEDS`,
   and the candidate texts of **the library the eval dispatches with**. Measured before any
   eval episode by `bench.similarity_probe.tune_baseline`. That function refuses an intent
   with fewer than two candidates, so an empty library cannot read as a failed baseline.
3. **What failing means.** Below the floor, no report may state that precondition dispatch
   beats text similarity. The comparison is still reported, with the floor's verdict beside
   it. A failed baseline is itself a finding about arm 2, and dropping the row would hide it.
4. **What stays ungated.** Figures on `PROBE_SEEDS` and on hand-written gold remain
   exploratory. The probe module's "never gated" rule holds for everything except
   `tune_baseline`.

## Consequences

**Accepted:** the floor is lenient. It asks only that arm 2 be distinguishable from chance,
not that it be good. A baseline at, say, 45% clears it, and arm 3 beating a 45% dispatcher
is a weaker statement than beating a strong one. The per-intent spread ADR-0003 records
(0.8125 vs 0.6007 AUC on the probe) is not judged separately, so one intent near chance can
hide behind the other. The floor also cannot be run for real until a compiled library exists.
Until then it is machinery plus a gold figure that is explicitly not the gate.

**Gained:** "preconditions beat text similarity" can no longer be read off a baseline that is
indistinguishable from a coin flip, and the rule was fixed before any eval data. The verdict
is produced by code with its counts, not left to whoever writes the prose.

**New obligations:** the eval run records `tune_baseline`'s row and the floor verdict before
its first eval episode. Any change to arm 2's scorer, representation or threshold re-measures
it, because the floor judges the arm as the eval runs it.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Point estimate above chance | One pair above chance (9/24) would pass. That is noise, and a comparison against it is against a coin flip. |
| A fixed absolute floor (e.g. 50%) | There is no principled number. Any fixed value above chance is a judgement about how good a baseline must be, which is a stronger claim than #116 asked for and would need its own justification. |
| AUC instead of top-1 | Dispatch acts on the argmax, and ADR-0003 showed AUC and top-1 can move in opposite directions (IDF raised AUC while lowering top-1). |
| Judge each intent separately | A stricter and arguably better rule, but at 16 tune seeds each intent has about 48 decidable pairs, and the per-intent spread is already reported under ADR-0003. Left as a possible tightening, not adopted. |
| Gate on the probe's figures | Those are exploratory (hand-written gold, seeds 0–3), and gating them is the proxy-threshold failure the probe's docstring rules out. |

## What would reverse this decision

- Evidence, before the eval, that a baseline which clears chance can still make the
  comparison vacuous. For example, arm 2 clearing the floor on one intent while sitting at
  chance on the other. That would argue for judging per intent (the rejected alternative
  above), through a new ADR before any eval episode.
- A change in how many candidates an intent declares. The chance rate is `1 / candidates`,
  so the floor is re-derived, not reversed.
- After eval data exists the floor cannot move. That is the point of registering it.
