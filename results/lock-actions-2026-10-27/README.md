# Which lock-file action reproduces the maintainer's: stage A's 30 conflicts, 2026-10-27 (#306)

**Exploratory.** This runs on the real-merge pilot's cases, which have already been seen. It
tests nothing; it shapes study 2, which will be registered before its data is mined.

```bash
python -m precondition_library.bench.lock_actions --stage results/real-merges-2026-10-26/stage-A \
    --out results/lock-actions-2026-10-27/stage-A.jsonl --work <scratch>
```

Stage A compared lock files as multisets of lines, and no maintainer's merge was either of the
intent's line unions (0 of 30). Here each lock file is read into its set of resolved
`(package, version)` pairs (`bench.lock_actions`). The question is put as a maintainer meets it:
given their merge of every other file, which action on the lock file gives the one they
committed?

## Result

| action | cases reproduced exactly |
| --- | ---: |
| `three_way_unified`: package-level three-way merge, each compatible range unified to its highest version | **6** |
| `take_local` | 4 |
| `three_way`: package-level three-way merge | 4 |
| `take_upstream` | 2 |
| `reconcile_local`: the local file reconciled by the ecosystem's tool today | 2 |
| `reconcile_upstream` | 2 |
| `regenerate`: the tool resolves from scratch today | 0 |
| **some action** | **10 of 30** |

The drift-tolerant comparison (same names, and the same versions for every package that existed
before the merge) reproduces exactly the same cases.

**Per lock file.** The median Jaccard similarity between an action's package set and the
maintainer's is 0.973 for `three_way`, 0.963 for `three_way_unified`, 0.931 for `take_local`,
0.805 for `take_upstream` and 0.196 for `regenerate`. Where the package merges miss, they miss
by a few packages.

## What it shows

- **The intent's idea was right, and its formulation wrong.** Stage A's line unions reproduced 0
  of 30. Their package-level counterpart reproduces 6, and is the best single action. Case 25
  (helix) is the clearest example: stage A put it in "other", while `three_way_unified`
  reproduces it exactly.
- **A third of real lock-file conflicts have a reproducible answer: 10 of 30.** Those can be
  labelled by what the maintainer did, with no tool and no judgement of ours.
- **The other 20 are near-misses, for one reason.** 27 of the 30 conflicts also conflict in
  other files, typically the manifests. The maintainer resolved those by hand and ran their tool
  on that day's registry, and no action taken today can replay that.
- **Running the ecosystem's tool today is the weakest oracle.** 51 of the 144 tool runs
  failed, and the failures are tooling, not merges: poetry 2 refuses old lock formats (all 18 of its runs
  failed); some cargo git dependencies name branches since deleted; old yarn workspaces point at
  paths that moved. The computed package-level actions avoid all of it.

## What it does not show

- **That any dispatcher picks the right action.** No library holds a package-level program yet.
  Building one is #307's.
- **Anything confirmatory.** The ten reproducible cases come from data already seen. Study 2's
  registration fixes the action set and the comparison before its data is mined.

`stage-A.jsonl` holds every case, lock file and action, with its Jaccard and any tool's error.
`run.log` is the run's output.
