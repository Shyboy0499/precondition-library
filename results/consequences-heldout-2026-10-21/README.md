# What held-out fires do when they are replayed, 2026-10-21

The held-out stage (`results/heldout-2026-10-1*/`) counts arm 3's choices on states with paths,
names and shapes no build saw. This directory replays each of those choices, and arm 2's, and
grades what it leaves: the same stage as `results/consequences-2026-10-21/` (ADR-0044) on the
held-out block (seeds 3000–3039, the five git faults). It is exploratory and model-free, and the
committed libraries are read-only.

```bash
python -m precondition_library.bench.consequences --run results/replicates-2026-10-05/run-N \
  --seeds held-out --out results/consequences-heldout-2026-10-21/run-N
```

Code: `c5d6e09`, after the four grader fixes this replay found (ADR-0045). Results graded before
them were discarded.

## The choices are the held-out stage's

Arm 3's fires and wrong fires are the sums of the committed held-out blocks: 193, 13 (run-11);
193, 8 (run-12); 195, 21 (run-13). Arm 2 fires at the threshold matched to arm 3's coverage on
this block, which is this block's operating point, not Figure 1's.

## Result

| | run-11 | run-12 | run-13 | all three |
| --- | ---: | ---: | ---: | ---: |
| **arm 3, correct choices** | 180 | 185 | 174 | 539 |
| fixed | 173 | 173 | 157 | 503 |
| not fixed | 7 | 5 | 17 | 29 |
| committed outside the change surface | 0 | 7 | 0 | 7 |
| **arm 3, wrong choices** | 13 | 8 | 21 | 42 |
| fixed | 0 | 0 | 0 | 0 |
| not fixed | 13 | 5 | 21 | 39 |
| committed outside the change surface | 0 | 3 | 0 | 3 |
| **arm 2, fires on a fault's state** | 85 | 77 | 76 | 238 |
| fixed | 44 | 46 | 24 | 114 |
| **arm 2, fires on a fault-free state** | 108 | 116 | 123 | 347 |
| of them, changed something | 0 | 0 | 0 | 0 |

The outcome `lost recorded state` in `consequences.jsonl` covers a commit outside the fault's
change surface, which is what all 10 here are. No replay lost a recorded commit or rewrote
upstream.

## What it shows

**Every arm-3 failure is a program's, and nearly all are on the lock file.** Each cause is read
from the checker's reason. The `web` file and the two run-13 programs were also confirmed by
rebuilding a case by hand.

- **Paths read without `-z`.** These are the held-out lock-file paths with a space or a non-ASCII
  name, the defect ADR-0038 found by reading the programs.
  - run-12's `take-upstream` loops `for f in $(git diff --name-only ...)`. On
    `web app/deps.lock` it writes and commits an empty file named `web`, and leaves the lock
    file conflicted. That accounts for the 10 commits outside the surface, and for 10 more fires
    on the non-ASCII path where markers remain.
  - run-11's `take-upstream` leaves upstream's tip out of the local branch on 7 correct and
    3 wrong fires.
- **The wrong `diverged` `discard` fires discard the local dependency change.** 10 in run-11 and
  20 in run-13 fire a `diverged` `discard` program on a lock-file state. Replayed, each leaves the
  local dependency change out of the branch: the checker reports "the locally-added dependency is
  missing". These are the held-out stage's worst mis-fires, and the replay shows what they would
  have cost. The other wrong fire in run-13 is a `dirty_tree` stash program after which the
  untracked work is not in the tree.
- **run-13's two programs from the eval replay fail here too.**
  - The `.local`-convention `aside`, 10 fires: the content is kept, against the checker's
    convention.
  - The `keep_local` whose awk filter drops upstream's pure insertions, 7 fires.

**Arm 2 again mostly does nothing where nothing was needed.** None of its 347 fires on fault-free
states changed anything. On a fault's state it fixed 114 of 238.

## What it does not show

- **A comparison with arm 2.** No held-out floor is measured, so no sentence may say arm 3 beats
  text similarity here (ADR-0033).
- **The episode stage.** Fires only; a miss is not solved.
