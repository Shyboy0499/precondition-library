# ADR-0019 — An overlap state is judged by the program's own intent, not as unrelated

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It narrows the unrelated-fault class of Claim 3's negative side; it does not reverse the two-sided gate.
- **Deciders:** repository owner

## Context

Admission's negative side (Claim 3) builds three classes of states a program must
reject: a fault-free sandbox, every *unrelated* fault's states, and its own fault's
sibling-resolution states. "Unrelated" was defined by which injector built the state:
any state another fault injects was treated as one where any fire is a defect.

The first live build (#163) showed that this definition is wrong for overlapping
families. `lockfile_conflict` seed 0 injects a diverged branch, one commit ahead and one
behind, whose two sides both changed `deps.lock`. The `sync_fork_with_upstream`
intent's own decision rule labels that state **merge**. Every compiled diverged
program was rejected there, so the frozen library held no diverged program, and half
the measurable task family dropped out of the comparison. The hand-written gold merge
program had only ever passed because of an extra precondition,
`local_work_beyond_the_overlap`, added earlier to dodge this exact state. That
precondition is a workaround for the overlap, not part of what "merge is correct"
means.

## Decision

1. For every state another fault injects, admission asks **this program's intent** to
   label it (`IntentSpec.correct_variant` on the observed state). It does this in the
   same sandbox build as the probes (`_preconditions_accept_labelled`).
2. A state the intent labels is an **overlap state**, and it is judged like a sibling:
   - a fire is **correct** when the program implements the label;
   - it is a **mismatch**, and the program is rejected with a reason naming the
     overlap, when the program implements anything else.
3. A state the intent leaves unlabelled stays **unrelated**: any fire is a defect, as
   before. Labelling rules that match a state more than once also count as unlabelled,
   so a defect in the rules can never make a state look like a legitimate place to
   fire.
4. Correct overlap fires count toward the breadth cap, since they are fires on the
   sampled universe.

## Consequences

**Gained:** the gate stops rejecting programs that are correct by the task family's
own labels. A merge program may fire on a lockfile conflict; a program mislabelled
`rebase` may not. The overlap state becomes evidence in the class where it belongs,
instead of being thrown away.

**Accepted:** the negative side now depends on the intents' decision rules being
right about *other* faults' states, not only about their own. A rule that labels a
foreign state wrongly would now admit a program that fires there. That dependency
already existed for the pairs' labels (`bench.pairs`), so the gate and the metric now
rest on the same rules rather than on different ones.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Exclude labelled states from the negative set altogether | Simpler, but it discards a state that can still catch a mislabelled program. As a same-intent state it keeps doing that. |
| Re-scope `lockfile_conflict` so it no longer injects a diverged branch | Fixes this pair of faults in the task family rather than in the gate, so the next overlapping fault would hit the same false rejection. |
| Keep the old definition, and rely on compiled programs adding a dodge like gold's `local_work_beyond_the_overlap` | Asks the compile step to anticipate a quirk of the negative set that nothing tells it about. It also rewards preconditions shaped by the gate rather than by the state. |

## What would reverse this decision

- An intent whose decision rule is found to label another fault's state incorrectly.
  The overlap class would then admit a wrong fire, and the fix would be to the rule;
  only a rule that cannot be fixed would argue for excluding overlap states instead.
