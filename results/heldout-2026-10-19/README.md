# Held-out states, part 4: new branch names and new submodule paths, 2026-10-19

Parts 1–3 gave held-out axes to `dirty_tree`, `diverged` and `lockfile_conflict`
(`results/heldout-2026-10-10/`, `-16/`, `-18/`). This part covers the last two git faults
(ADR-0042):

- **`branch_renamed`, held-out names.** Upstream renames its default branch to `release/2026`,
  `main-v2`, `stable.next` or `team/integration`. The shipped names are `trunk`, `develop`,
  `default` and `primary`. Two of the held-out names contain a `/`.
- **`submodule_moved`, held-out paths.** The submodule lives at `third_party/libs/core`,
  `.deps/libcore`, `lib/core-v2` or `ext/libcore` instead of `vendor/libcore`.

Every value is shell-safe (ADR-0040), so it binds. Every label is kept: all 80 held-out states
were built with the label check on, and four of each were resolved by the gold programs at
their own name or path.

No model call, no rebuild: each committed frozen library is read-only, with its digest
compared before and after. Code: the commit that adds this directory.

```bash
python -m precondition_library.bench.heldout --run results/replicates-2026-10-05/run-N \
  --faults branch_renamed --out results/heldout-2026-10-19/branch_renamed/run-N
python -m precondition_library.bench.heldout --run results/replicates-2026-10-05/run-N \
  --faults submodule_moved --out results/heldout-2026-10-19/submodule_moved/run-N
```

## Result

Seeds 3000–3039, uninformed regime, the lexical arm 2. Each block has 40 held-out positive
states and 40 fault-free negatives.

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| `branch_renamed`, held-out names: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| `submodule_moved`, held-out paths: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| fires on the 40 fault-free negatives (each block) | 0 | 0 | 0 |

Every count was re-derived through a second path. Each state was built again and matched
directly, with the fired program checked against the fault's own acceptable resolutions. The
second path agrees on all six blocks: every held-out name and path drew 10 fires of 10, none
wrong.

## What it shows

**Both axes carried completely: 240 fires, all correct.** The reason is in the programs. None
of the 20 compiled programs for these two faults names a branch or a submodule path. Every one
reads the value through its bound parameter, `{upstream_branch}` or `{submodule_path}`, so a
new name or path reaches it as the value it already asks for.

**Compare the lock-file block (part 3, 41 of 101 wrong).** There the file's path is not a
parameter. A program has to find it in git's printed path lists, and that reading is what
broke on a space or a non-ASCII name. So far:
- a held-out value the runtime hands a program has never broken it;
- a value the program has to read out of git's output has broken it.

## What it does not show

- **A comparison with arm 2.** No held-out floor is measured, so no sentence may say arm 3
  beats text similarity here (ADR-0033).
- **Unsafe names.** A branch or submodule path with a space or a metacharacter is left
  unbound by design (ADR-0040), so programs needing it refuse. Those values are not drawn
  here, because they would measure the binding screen, not the programs.
- **Real repositories.** These are still the generator's states with new values.
