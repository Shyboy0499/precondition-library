# Why arm 3 sits out: its misses on the three replicate libraries, 2026-10-12

Arm 3 fires on 187, 187 and 189 of each library's 200 positive pairs and on none of the 200 fault-free
negatives (README, Primary result). `bench.abstentions` names every positive it misses, and why. No
model call, no rebuild, the committed frozen libraries read-only:

```bash
python -m precondition_library.bench.abstentions --run results/replicates-2026-10-05/run-N \
  --out results/abstentions-2026-10-12/run-N
python results/abstentions-2026-10-12/own_state.py > results/abstentions-2026-10-12/own_state.tsv
```

Each `run-N/` holds `abstentions.jsonl` (one row per miss: the pair, the state, every candidate
program and each precondition that failed, with what it observed), `abstentions.json` and
`summary.txt`. `own_state.tsv` says, for every admitted program, whether its preconditions hold on
the state it was learned on. Code: main at `28bd85b` plus this branch.

## The counts reproduce Figure 1

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| positives / negatives | 200 / 200 | 200 / 200 | 200 / 200 |
| arm 3 fires (on negatives) | 187 (0) | 187 (0) | 189 (0) |
| positives arm 3 sat out | 13 | 13 | 11 |

Every miss is a `lockfile_conflict` state. The other four faults' positives were all fired on, in all
three libraries.

## Three different causes

| run | misses | state | cause |
| --- | --- | --- | --- |
| run-11 | 13 | needs `keep_local` | **No program.** The library learned no `keep_local` program. The replicate README's provenance row says why: both lockfile programs met the awk defect. |
| run-12 | 13 | needs `keep_local` | **A dead program.** `lockfile_conflict-occ2-lockfile-merge-keep-local-removals` was admitted, but its preconditions fail on every `keep_local` state, **including the one it was learned on** (seed 2, `own_state.tsv`). |
| run-13 | 11 | needs `take_upstream` | **Checks too narrow.** Both lockfile programs' preconditions hold on the state each was learned on, but `upstream_dropped_lines_local_still_has` (`take_upstream`) and `local_side_drops_lines_in_shared_file` (`keep_local`) fail on the 11 other `take_upstream` instances. |

**Why the dead program was admitted.** Admission's positive side (`agents.compile._positive_refusal`)
**replays** the program on its learning state, running the body and checking the postconditions. It
never evaluates the program's **preconditions** there. The negative side refuses states the
preconditions wrongly accept, and the breadth cap refuses preconditions that accept too much.
Nothing refuses preconditions that accept nothing. A program whose checks never hold passes every
side: its replay works, and it refuses every negative because it refuses everything. `own_state.tsv`
finds exactly one such program among the 40 admitted.

**Why its checks never hold.** `three_way_merge_conflicts` runs
`git merge-file -p <(git show …) <(git show …) <(git show …)`. Under this machine's git 2.43,
`git merge-file` given process substitutions reads them as empty and prints nothing, so the check
never sees a conflict marker. A three-line reproduction with regular files conflicts as expected,
and the same files through `<( )` print nothing.

## What it shows

- **All the coverage arm 3 loses comes from one fault family.** Every miss is a `lockfile_conflict`
  state, and it never fires a wrong program instead.
- **Two of the three causes are the library, not the dispatcher**: a resolution never learned
  (run-11), and a program admitted without ever being able to fire (run-12).
- **An admission gap.** Requiring the preconditions to hold on the positive seeds would have refused
  the run-12 program. It would have been sent back with that reason, which is what ADR-0030's one
  revision is for. That change would move admission, so it needs a decision of its own.

## What it does not show

- How often a check this narrow (run-13) or dead (run-12) occurs in general: one family, three
  libraries.
- Whether `git merge-file` on process substitutions behaves differently under another git version.
  The build did not record its git version, and on this one the check cannot pass.
