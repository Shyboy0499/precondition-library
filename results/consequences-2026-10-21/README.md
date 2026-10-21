# What a dispatch decision does when it is replayed, 2026-10-21

Figure 1 counts a mis-fire as a wrong *choice*. This directory replays every choice and grades
what it leaves (ADR-0044). It is **exploratory**, not the pre-registered episode stage: nothing
here solves a miss, so it measures fires only.

For each of the 400 eval pairs per library (seeds 2000–2039, the five git faults, the
uninformed regime), the arms decide exactly as Figure 1 decided:
- arm 3 fires its first accepted program;
- arm 2 fires its top-1 when the score reaches its **matched threshold**, the one at which
  Figure 1 matched it to arm 3's coverage.

Each fired program is replayed on a fresh build of the pair's state, then graded:
- **On a fault's state**, by the two clauses the episode loop grades every episode with: the
  recorded state is intact over the fault's change surface, and the fault's own checker passes.
- **On a fault-free state**, by whether anything moved: HEAD, the branch, both repositories' refs
  and the working tree's status, before against after.

No model call. Each committed frozen library is read-only, with its digest compared before and
after. Code: the commit that adds this directory.

```bash
python -m precondition_library.bench.consequences --run results/replicates-2026-10-05/run-N \
  --out results/consequences-2026-10-21/run-N
```

Each `run-N/consequences.jsonl` has one row per fire: the arm, the pair, the program, whether
Figure 1 counted it correct, the outcome and the checker's reason.

## The decisions are Figure 1's

Each run's matched threshold and arm 2's wrong fires at it are exactly the committed primary
report's (`results/replicates-2026-10-05/run-N/primary/primary.txt`):

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| arm 2's matched threshold | 0.13423 | 0.13592 | 0.14516 |
| arm 2 fires, wrong (Figure 1) | 187, 148 | 185, 149 | 187, 143 |
| arm 3 fires, wrong (Figure 1) | 187, 0 | 187, 0 | 189, 0 |

## Result

| | run-11 | run-12 | run-13 | all three |
| --- | ---: | ---: | ---: | ---: |
| **arm 3**: fires, all on a fault's state | 187 | 187 | 189 | 563 |
| fixed | 187 | 187 | 162 | 536 |
| not fixed | 0 | 0 | 27 | 27 |
| **arm 2**: fires on a fault's state | 89 | 71 | 81 | 241 |
| fixed | 51 | 49 | 47 | 147 |
| not fixed | 38 | 22 | 26 | 86 |
| nothing ran (an unbindable parameter) | 0 | 0 | 8 | 8 |
| **arm 2**: fires on a fault-free state | 98 | 114 | 106 | 318 |
| changed nothing | 89 | 105 | 77 | 271 |
| nothing ran | 9 | 9 | 29 | 47 |
| changed something | 0 | 0 | 0 | 0 |
| any fire that lost a recorded commit or rewrote upstream | 0 | 0 | 0 | 0 |

A rerun of run-11 from scratch reproduced `consequences.jsonl` and the summary exactly.
After the grader fixes of ADR-0045 (code `c5d6e09`), all three runs were replayed again and
reproduced their `consequences.jsonl` byte for byte: no eval state met a defective clause.


## What it shows

**A correct choice is not always a correct outcome.** Every arm-3 fire is a correct choice, and
in runs 11 and 12 every one also fixed the state. In run 13, 27 of 189 did not. The cause is two
of that library's admitted programs. Both exit cleanly and pass their own postconditions, and
the checker refuses what they leave:

- **`dirty_tree-occ3-upstream-sync-wip-aside`**, 14 fires. It copies each changed file to
  `<path>.local` and resets the tree. The checker allows a `.local` copy only for a colliding
  untracked file, and requires a tracked edit to stay in the tree, so it refuses. The content is
  not lost: it is in the `.local` copy (checked on seed 2000). The program was compiled from a
  solve the checker had already refused (`build.jsonl`: `ground_truth_ok: false`). An arm may not
  read the checker (issue #9), so admission judged the program by its own postconditions, which
  this body meets.
- **`lockfile_conflict-occ3-merge-upstream-keep-local-depfile`**, 13 fires. Its awk filter keeps
  upstream's added lines only from hunks that also delete a line, so a pure insertion is dropped.
  The checker refuses with "the upstream-added dependency is missing". The solve it was compiled
  from passed, on a state where the filter's defect did not show.

**Arm 2's mis-fires mostly do nothing; on a fault's state they mostly fail.**
- Of its 559 fires, 318 are on fault-free states. Not one changed anything: 271 ran and left
  the repository as it was, and 47 could not bind a parameter.
- On a fault's state, 147 of 241 fires fixed it. That includes 40 Figure 1 counts as wrong
  (18, 13 and 9). Most are a `repin`, `merge` or `commit` program on a `submodule_moved` state
  that happens to leave the submodule as upstream has it. The checker passes, usually while the
  program's own postconditions fail.
- The 86 fires that did not fix the state left, for example:
  - the branch tracking a ref upstream no longer has;
  - conflict markers in `deps.lock`;
  - upstream's tip missing from the local branch;
  - a rebase stopped mid-conflict.

  On the one I opened (run-12, seed 2004), the checker's reason says the untracked work was
  "discarded". In fact it had been committed, and the rebase stopped on an add/add conflict.
- No replay of either arm lost a recorded commit or rewrote upstream's history.

**Figure 1 grades a choice by its variant's name.** 88 of arm 2's fires on a fault's state were
another fault's program (40, 20 and 28). Figure 1 counts one correct when the names match: six
`diverged` `merge` fires on `branch_renamed` states in run-11, which did not fix them. That
flatters arm 2, the baseline, so it does not inflate the comparison. Arm 3 never fired another
fault's program.

## What it does not show

- **The episode stage.** A miss here is not solved by the agent, so there is no success rate per
  pair, no cost and no comparison of arms' episodes.
- **A rate for "correct outcome" that generalises.** Run 13's 27 come from two programs in one
  library. The other two libraries had none.
- **Harm beyond what the grader reads.** The grader reads the recorded state, the fault's checker
  and, on a fault-free state, a snapshot of refs and status. A body that wrote outside the
  repository is the guard's concern and is not measured here.
