# ADR-0016 — Arm 2b is a soft vote over arm 3's probes, and a tie with arm 3 restates Claim 2

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing (third of issue #7's four baselines; ADR-0014 and ADR-0015 are the first two)
- **Deciders:** repository owner

## Context

Claim 2 says executable-precondition dispatch mis-fires less than text-similarity
dispatch at matched coverage. Arm 3 does two things at once: it reads the
environment through probes, and it combines them with a **hard conjunction**
(every precondition must hold). A win for arm 3 over arm 2 could come from either.
Issue #7 asks for arm 2b to separate them: "a soft classifier over the SAME probe
features as arm 3, learned threshold -- if 2b ties arm 3, hard conjunctive
executable predicates add nothing over the same information, and the honest claim
becomes 'probe-based dispatch beats text-similarity dispatch'."

Three things were the owner's to choose: what the classifier is, how its threshold
is learned, and what "ties" means.

## Decision

1. **The classifier is a soft vote.** A program's score is the fraction of its
   preconditions that hold (`library.soft_vote_score`), read from the same
   `evaluate_preconditions` results arm 3 reads `.ok` from: no extra probing and no
   other features. A program with no preconditions scores 1.0 (arm 3 accepts it
   too), and a refused probe counts as not holding (as for arm 3). Programs are
   ranked by score, then specificity, then id, which is arm 3's tie-break, so **arm
   3 is the vote at threshold 1.0**. A test pins that the two make identical choices
   there on real sandboxes.
2. **The threshold maximises tune-set accuracy** (`bench.soft_vote.learn_soft_threshold`):
   most correct decisions, where firing the right variant and abstaining on a state
   that needs nothing are both correct. Ties go to the stricter floor, and abstaining
   everywhere (`NEVER_FIRES`) is always a candidate. Tune outcomes are collected on
   real sandboxes (`soft_vote_outcomes`): each tune seed's faulted state is a positive
   and its clean sandbox a negative.
3. **The arm** (`Arm.SOFT_VOTE`) runs through the shared dispatch path, behind
   `Library.match_soft` and `dispatch_soft_vote`. It records its score in
   `dispatch_score` and its threshold in a new `soft_threshold` field. `Library` and
   `run_benchmark` **refuse** to run 2b without a learned threshold, because a
   default would be recorded as if it had been tuned.
4. **Restating Claim 2** (spec §7 item 12, `claim2_verdict`): 2b's swept curve is
   matched to arm 3's coverage by the primary metric's own rule. The two per-fire
   mismatch rates are then compared by the success-rate TOST already pre-registered,
   at the same ±10pp margin and α. *Equivalent* restates Claim 2. The exception: a
   matched point at threshold 1.0 **is** arm 3. Its equivalence is a tautology, so it
   is reported as **collapsed** and keeps the registered wording.

## Consequences

**Found while building it, and the reason for decision 4's exception.** On
hand-written gold at the tune seeds (64 outcomes), the most accurate threshold is
**1.0**. Lowering it to 0.5 fires on all 64 and gets 32 wrong. A plain "equivalent at
matched coverage" rule would therefore have restated Claim 2 when the data had in
fact *chosen* the hard conjunction. This is an exploratory figure on gold, not the
eval; compiled programs may well behave differently, which is what the eval measures.

**Accepted:** the vote has only one learned parameter, so a richer classifier
(logistic regression, per-predicate weights) could still beat it on the same
features. A tie here shows that one simple soft rule matches the conjunction, not
that every soft rule would. The rejected alternatives below are the stronger
versions, and the soft vote was chosen because it isolates exactly one change from
arm 3.

**New obligations:** the learned threshold is a tune-pass output and goes on every
2b row. Learning it needs a compiled library and the tune seeds, the same
precondition as arm 2's floor (ADR-0007).

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Logistic regression over per-(state, program) summary features | More expressive, but fit on few tune pairs, and it would add a learned model whose own fitting choices become part of the result. The soft vote changes exactly one thing relative to arm 3. |
| Per-predicate learned weights | Predicate names differ between compiled programs, so weights learned on one library generalise poorly to another, and the frozen library is compiled once. |
| Threshold chosen to match arm 3's tune coverage | Picks 2b's operating point from arm 3's behaviour instead of from 2b's own accuracy, which builds the comparison into the baseline. |
| "Ties" = equivalent mismatch at matched coverage, with no exception | Restates Claim 2 when the soft vote collapses to the hard rule, as it does on gold: a tie between two names for one decision procedure. |

## What would reverse this decision

- An eval run where 2b's matched point sits below 1.0 and is TOST-equivalent to arm
  3. Claim 2 is then restated by this ADR's own rule. That is the decision
  working, not being reversed.
- Evidence that the vote's single threshold is too weak a competitor, for instance a
  logistic fit on the same features beating it clearly on the tune set. A richer
  2b would then be required before a "hard conjunction adds value" reading could be
  stated.
