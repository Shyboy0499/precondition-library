# A library-scoped control on stage B, exploratory (ADR-0052)

**Exploratory, not a test.** Stage B's data had been seen when this control was written, and it
was written because of what stage B showed. Nothing here supports or refutes a registered
hypothesis. It asks one question, to shape the next registered study: does ADR-0052's reading of
H2 hold?

ADR-0052 found that the registered state-reading control decides with the lock-file intent's own
tree. It can fire only that intent's resolutions, while arm 3 fires any program in the library. So
H2's margin could be what each is allowed to fire, not how each decides. This rerun gives the
control arm 3's scope. `StateClassifier.decide_library` reads every intent's tree, the same trees
fitted on the same 56 states. It fires the most probable resolution any of them predicts. The
registered H2 and H3 tests are then applied unchanged (`bench.library_control`).

## The states

`../states.jsonl.gz` holds each of the 274 cases' observed state, rebuilt from the manifest by
`real_merges.observe_states`. On every one, the registered control, which is deterministic and
reads only the state, decides exactly as the run recorded, so every state rebuilt as it was (274
of 274).

## What the control does

| | fires | right |
| --- | ---: | ---: |
| library-scoped control, clean merges | 112 of 113 | 110 |
| library-scoped control, conflicts | 161 of 161 | 0 |
| registered control, clean merges | 0 of 113 | 0 |
| registered control, conflicts | 160 of 161 | 1 |

It fires `merge` on 270 cases, `rebase` on 2 and `take_upstream` on 1. On 160 of the conflicts its
`merge` comes from the `sync_fork_with_upstream` tree. That intent's rule refuses a sync that would
conflict, but only 4 of the 56 training states conflict, all of them lock-file states. So the tree
never learned to refuse on that feature in general, and it fires `merge` on real conflicts. Arm
3's compiled `merge` programs run a check that tries the merge, and refuse when it would conflict.

## Against arm 3, per library

| | run 11 | run 12 | run 13 |
| --- | --- | --- | --- |
| arm 3: fires, wrong | 150, 62 | 122, 10 | 244, 132 |
| control: fires, wrong (one operating point) | 273, 163 | 273, 163 | 273, 163 |
| H2 with this control [cluster bootstrap] | +0.184 [−0.014, +0.416] | +0.515 [+0.381, +0.668] | +0.056 [+0.018, +0.111] |
| McNemar on joint fires (only arm 3 right / only control right) | 3 / 26 | 2 / 1 | 2 / 1 |
| H3 with this control [cluster bootstrap] | +0.775 [+0.615, +0.896] | +0.944 [+0.860, +0.990] | +0.181 [+0.053, +0.345] |

**The coverage is not matched.** Every score the control gives is 1.0, so its curve has a single
point, at 273 fires, and it cannot be swept down to arm 3's 122–244. H2's figures here therefore
compare unequal coverage, which favours the dispatcher that fires less. They are reported because
the registered test produces them, not as a comparison at matched coverage.

## What it shows (exploratory)

- **ADR-0052's reading holds.** Once the control may fire `merge`, it is right on clean merges as
  often as arm 3 (110 of 112). On the cases both fire, arm 3 is not the better one: in run 11 the
  control is right where arm 3 is wrong 26 times, against 3.
- **What separates them is refusal.** On conflicts nothing can resolve, the control fires every
  time, and two of the three libraries mostly decline (H3). In this data, that is the one place
  where executing a check differs from reading the state. Arm 3's merge programs try the merge and
  refuse a conflict, while a tree fitted on 56 synthetic states never learned to.
- **Study 2 should test refusal directly.** That is the property #307 builds for, through
  refusal-tested admission over a population of builds. It should be measured against a control
  that may fire what arm 3 may, and on cases no one has seen.

## What it does not show

- Anything registered: these cases and this question were chosen after the data was seen.
- That a better-trained classifier would not refuse too. A tree trained on states that include
  conflicting syncs might learn the rule. The point is that this one, fitted as registered, did
  not.
- The LLM state judge (#295), which reads the state through a model call. It has not been run.

## Files

- `report.json`, `summary.txt`: as `python -m precondition_library.bench.library_control
  results/real-merges-2026-10-26/stage-B --out <this directory>` wrote them.
- `../states.jsonl.gz`: the recorded states, compressed (`python -m precondition_library.bench.real_merges
  --observe-states results/real-merges-2026-10-26/stage-B`).
