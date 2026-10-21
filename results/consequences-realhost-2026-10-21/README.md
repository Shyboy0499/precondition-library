# What fires do when replayed over real repositories' histories, 2026-10-21

`results/realhost-2026-10-20/` showed that arm 3 *chooses* the same programs on the eval states
whether each state's history is the generator's two-file base or a pinned public repository's
(ADR-0043). This directory replays those choices, and arm 2's, on the real-host base and grades
what they leave: the same stage as `results/consequences-2026-10-21/` (ADR-0044), with every state
built over the real history. Exploratory and model-free; the committed libraries are read-only.

```bash
python -m precondition_library.bench.consequences --run results/replicates-2026-10-05/run-N \
  --real-host --out results/consequences-realhost-2026-10-21/run-N
```

Code: `c5d6e09`, after the four grader fixes this replay and the held-out one found (ADR-0045).

## Result

**Every row agrees with the synthetic base.** For each library, every row of `consequences.jsonl`
-- arm, pair, program, whether Figure 1 counted it correct, and outcome -- equals the
synthetic-base replay's row (`results/consequences-2026-10-21/`): 374, 372 and 376 rows.

| | run-11 | run-12 | run-13 |
| --- | ---: | ---: | ---: |
| arm 3 fires, fixed | 187, 187 | 187, 187 | 189, 162 |
| arm 2 fires on a fault's state, fixed | 89, 51 | 71, 49 | 81, 47 |
| arm 2 fires on a fault-free state, changed something | 98, 0 | 114, 0 | 106, 0 |

Only the checker's reason text can differ, where it names a real file.

## What it shows

**The real history changed nothing about what a fire does.** Run-13's 27 failures are its two
programs that fail on the synthetic base too (ADR-0044); nothing new failed over a real tree.

**Getting there needed a grader fix (ADR-0045).**
- Before them, the lock-file checker read the `=` underline of every host's `HISTORY.md` or
  `README` as a leftover conflict.
- It graded 27 of run-11's and 43 of run-13's correct fires as not fixed. The underline alone
  accounts for 27 and 16 of them. The other 27 in run-13 are its two failing programs; the
  underline was simply the first clause to refuse 13 of them.
- Every hand-written gold program now passes on all 414 real-host states where its resolution
  is accepted.

## What it does not show

- **Real faults.** The history is real, and the fault is still the generator's.
- **Repositories in general.** Four pinned projects.
- **The episode stage.** Fires only.
