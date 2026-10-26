# A state-reading control matches arm 3, 2026-10-26 (#295)

Every state's correct resolution is defined as a rule over the observed `StateFingerprint` (each
intent's `decided_by`). So a dispatcher that recovers the rule from the state wins Figure 1
whether or not it executes anything. This directory measures one: a decision tree per intent over
generic features of the fingerprint, with no model call and no compiled program
(`bench.state_classifier`, ADR-0047).

```bash
python -m precondition_library.bench.state_classifier --out results/state-classifier-2026-10-26
```

- **Features.** Every fingerprint field as a scalar (a boolean, a count, a list's length), the size
  of every pair of list fields' overlap, and whether every pair of string fields is equal. None
  encodes an intent's rule.
- **Training.** The 56 states the libraries were built from: the five faults' admit seeds
  (0–8, 10) and the fault-free state at each. They are labelled by the intents' rules, the same
  label source admission is validated against. One tree per intent, default hyper-parameters,
  `random_state=0`.
- **Scoring.** Figure 1's pairs, built and labelled by the same code, graded by `bench.coverage`.
  The training seeds are disjoint from both blocks.

## Result

| | fires on 400 pairs | wrong |
| --- | ---: | ---: |
| **eval** (seeds 2000–2039), fingerprint classifier | 190 | 0 |
| eval, arm 3 (Figure 1, runs 11, 12, 13) | 187, 187, 189 | 0, 0, 0 |
| eval, arm 2 at arm 3's coverage | 187, 185, 187 | 148, 149, 143 |
| **held-out** (seeds 3000–3039), fingerprint classifier | 200 | 0 |
| held-out, arm 3 (the held-out stage) | 193, 193, 195 | 13, 8, 21 |

On eval, the classifier abstains on 10 positives, all `diverged`. The rule needs
`upstream_behind` above 0; the tree learned above 1.5. Of the 7 training states with exactly one
local-only commit, only one was `diverged`; the other six are other faults' states, which this
intent labels none. So the tree groups a one-commit divergence with them, and refuses those eval
states rather than mis-firing. On held-out it fires on every positive and on no fault-free state.

## What the trees learned

`trees.txt` prints each tree. They have depth 2 to 6, and each splits on the fields its intent's
rule reads. For example, `restore_submodule_state` splits on `has_submodule_reference`, then
`upstream_still_references_submodule`, then `submodule_pin_matches_upstream`. That is the rule.
The `diverged` tree splits on `upstream_behind`, the field behind the rule's
`has_local_only_commits`, at 1.5 rather than 0.5, learned from 56 states. That threshold is where
its 10 eval abstentions come from.

## What it shows

**On this project's own labels, compiled executable preconditions add nothing over reading the
state.**
- A tree over the harness's observation, fit on the build's 56 states, matches arm 3's coverage
  and mismatch on eval.
- On held-out it beats arm 3: no wrong fire against 8–21. Arm 3's held-out failures are its
  programs' path handling, which the observation already does correctly (ADR-0039).
- Figure 1's gap is reading the state against not reading it. It is not executable checks against
  similarity.

## What it does not show

- **That executability is worthless.** The classifier reads the harness's `StateFingerprint`,
  which this project engineered with the rules in view. Arm 3's probes compute their own
  observations from raw git, on any repository. Whether that matters is #295 item 3 (a control
  limited to what a probe can see) and #296 (real merges, labels we did not write).
- **The LLM state judge.** It needs a key and has not run.
- **Anything about real repositories' faults.** Every label here is the intents' rule (#294).
