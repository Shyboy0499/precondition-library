# ADR-0047 — A state-reading control matches arm 3 on the project's own labels

- **Status:** accepted
- **Date:** 2026-10-26
- **Supersedes:** nothing. It qualifies what Figure 1's comparison shows; no registered metric,
  denominator or figure changes.
- **Deciders:** repository owner (#294, "open all the issues, and reconstruct everything").

## Context

Figure 1 compares arm 3, which runs executable preconditions, with arm 2, which scores text
similarity. The claim drawn from it is that dispatching by executable checks mis-fires less than
dispatching by similarity.

But each state's correct resolution is defined as a rule over the observed `StateFingerprint`:
each intent's `decided_by` (#294). The comparison therefore never separated two things:
*executing compiled checks*, and *reading the state at all*. Arm 2 cannot evaluate the state, and
arm 3 can, so a dispatcher that reads the state without any compiled program is the missing
control (#295).

## Decision

1. **`bench.state_classifier` is that control.** It is a decision tree per intent over generic
   fingerprint features, fit on the 56 states the libraries were built from and labelled by the
   intents' rules. It is scored on Figure 1's pairs by Figure 1's code, with no model call and no
   compiled program.
2. **It is reported beside Figure 1 wherever Figure 1 is**, and the headline claim is narrowed to
   what both together support.

## What it found

- **Eval.** 190 of 400 pairs fired, none wrong. Arm 3 fired 187–189, none wrong.
- **Held-out.** 200 fired, none wrong. Arm 3 fired 193–195, with 8–21 wrong.
- **The trees recover the rules.** They have depth 2 to 6 and split on the rules' own fields
  (`results/state-classifier-2026-10-26/`).

**On this project's labels, compiled preconditions add nothing over reading the state.** Figure 1's
gap is reading the state against not reading it.

## Consequences

**Accepted:** the headline "precondition dispatch beats similarity" is restated as "a dispatcher
that reads the state beats one that does not, and compiled preconditions are one such
dispatcher". No sentence may say executability itself is what wins, until a control limited to
what probes can see (#295 item 3), or labels this project did not write (#296), shows it.

**Gained:** the comparison that decides whether the project's mechanism matters is now explicit,
and it is cheap to rerun.

**New obligations:** every future comparison, real merges included, reports this control beside
arm 3.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Hand-written features matching the rules | It would prove the obvious; generic relations let the tree find the rule, or fail to. |
| Training on eval states | It would measure memorisation; the build's own states are what arm 3 learned from. |
| Leave Figure 1's wording as it is | The control shows the wording claims more than the measurement separates. |

## What would reverse this decision

A control limited to what a learned program's probes can observe, or a set of labels this
project did not write, on which arm 3 beats the state-reading control.
