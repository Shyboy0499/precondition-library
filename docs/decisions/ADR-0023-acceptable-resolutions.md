# ADR-0023 — A mismatch is a fire outside the resolutions a state accepts

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It narrows ADR-0008's definition of a wrong fire. ADR-0008's arithmetic is unchanged.
- **Deciders:** repository owner

## Context

Each ambiguous intent labels each state with **one** resolution (`decided_by`), and
everything that scored a decision compared the fired resolution with that label:
- the pair metric (ADR-0008);
- the 2b tuning;
- the ledger's `misfired` and online demotion;
- admission's sibling and overlap classes (ADR-0019).

The fault checkers grade "the outcome, not the method". In the second live run (#163)
the model rebased successfully on two `merge`-labelled diverged states, and the checker
passed both times. The resulting `rebase` programs were rejected as mismatches, and the
library got no diverged program (#172).

The owner chose **multiple** acceptable resolutions per state. Before changing anything
I measured what "acceptable" means, by replaying every gold body on every injected state
over 60 seeds, with its conditions stripped, under the fault's own checker:

| `diverged` state | discard | merge | rebase |
| --- | --- | --- | --- |
| discard | ✅ | ✅ | ✅ |
| merge | ❌ | ✅ | ✅ |
| rebase | ❌ | ✅ | ✅ |

On `submodule_moved`, exactly one resolution passes in each state, and it is the label.

## Decision

1. **Acceptable is what the checker passes.** `ResolutionVariant.accepted_by` declares
   the labelled states where a resolution is acceptable besides its own.
   `IntentSpec.acceptable_variants(state)` returns the label plus those. For an
   unlabelled state it returns `()`, so a negative stays a negative.
2. **The declaration is held to the checker.** `tests/test_acceptable_variants.py`
   replays every gold body on every injected state and requires the checker's verdict
   to equal membership in the declared set, in both directions.
3. **One rule, everywhere.** `program.accepts(label, acceptable, fired)` decides
   whether a fire is right. It is used by:
   - the pair metric: `LabelledPair` and `PairOutcome` carry the set, which drives
     `operating_point`'s mismatch and `vacuous_reason`;
   - the 2b tuning;
   - `EpisodeRecord.misfired`: rows record `acceptable_variants`, and a row without it
     reads as the label alone;
   - online demotion's mismatch count;
   - admission's sibling and overlap classes. A fire on a state that accepts the
     program's resolution is correct there, and it counts toward the breadth cap.
4. **The label stays.** It is still the canonical resolution: the gold oracle replays it,
   the informed wording keys on it, and the text-similarity probes score against it.

## Consequences

**Gained:**
- A program is never rejected, and a fire never counted wrong, for a resolution that
  leaves the repository correct.
- The gate, the metric and the ledger agree, because they share one function.

**Accepted:**
- **`diverged` narrows.** Merge and rebase are acceptable on every diverged state, so
  the only wrong fire left there is `discard` on real local work. The intent now tests
  whether a dispatcher avoids the destructive resolution, not which of three it picks.
  `submodule_moved` remains a genuine three-way choice, so Claim 2's three-way evidence
  now comes from it alone.
- **The text probes keep the single label.** `bench.similarity_probe` and
  `bench.textcontrol` measure whether request text predicts the label. Their recorded
  baselines (ADR-0003, ADR-0004, ADR-0007) are not recomputed. They are diagnostics of
  the text channel, not the claim's metric.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Make the `diverged` checker enforce the label, e.g. require a merge commit on overlapping files | It would turn a stipulated preference into ground truth with no reason a rebase is wrong there. The sandbox has no published history for a rebase to rewrite. |
| Keep single labels and state that mismatch measures preference | The owner chose multiple. It would also leave the spec's mis-fire ("a program that runs, claims success, and did not") disagreeing with what is counted. |
| Derive the acceptable set by running the checker at scoring time | Scoring would need every resolution executed on every state, and the declaration would hide inside a side effect. A declared set, held to the checker by a test, stays reviewable. |

## What would reverse this decision

- A reason rebase is wrong on overlapping files that the sandbox can express, such as
  published history or a reviewer-visible conflict resolution. The checker should then
  enforce it, and the set would shrink back toward the label.
- `submodule_moved` losing its single-acceptable shape. Claim 2 would then have no
  three-way intent left, and the task family would need a new ambiguous fault.
