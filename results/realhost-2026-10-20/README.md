# Held-out states, part 5: real repositories' histories, 2026-10-20

Parts 1–4 (`results/heldout-2026-10-10/` to `-19/`) changed a name, a path or a shape inside the
generator's two-file base. This part changes the base (ADR-0043). Each sandbox's history starts
from a pinned public repository, its pinned commit and the 50 commits before it. The generator's
base is committed on top, and the fault is injected as before.

| host | commit | seeds |
| --- | --- | --- |
| [`psf/requests`](https://github.com/psf/requests) | `611c6162cbc4ac2020a2f91c7cfa4f3abf9bbb60` | 2000, 2004, …, 2036 |
| [`pallets/click`](https://github.com/pallets/click) | `2247b35ea1c47c727d7a06e51fa280e12a863ff6` | 2001, 2005, …, 2037 |
| [`junegunn/fzf`](https://github.com/junegunn/fzf) | `55c122f1a0e1340546c8709682bea5561fe0e8fd` | 2002, 2006, …, 2038 |
| [`expressjs/express`](https://github.com/expressjs/express) | `0dee2c52c7c873498f8ed7d8ee4ddd0a04d3ada8` | 2003, 2007, …, 2039 |

The seeds are the eval block, so each state is one Figure 1 measured on the synthetic base: the
comparison is paired. No model call, no rebuild: each committed frozen library is read-only, with
its digest compared before and after. Measuring fetches each host once, by commit; nothing of
theirs is committed here. Code: the commit that adds this directory.

```bash
python -m precondition_library.bench.realhost --run results/replicates-2026-10-05/run-N \
  --out results/realhost-2026-10-20/run-N            # optionally --hosts one per process
python -m precondition_library.bench.realhost --out results/realhost-2026-10-20/run-N --summarize
```

Each `run-N/<host>/<fault>/` is one `bench.heldout` block: 10 positives and 10 fault-free
negatives. `run-N/realhost.json` holds the pins and every block's counts, read back from the
blocks.

## Result

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| `dirty_tree`: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| `diverged`: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| `lockfile_conflict`: arm 3 fires, mis-fires | 27, 0 | 27, 0 | 29, 0 |
| `branch_renamed`: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| `submodule_moved`: arm 3 fires, mis-fires | 40, 0 | 40, 0 | 40, 0 |
| all 200 positives: fires, mis-fires | 187, 0 | 187, 0 | 189, 0 |
| fires on the 200 fault-free negatives | 0 | 0 | 0 |
| Figure 1, synthetic base, same seeds: fires, mis-fires | 187, 0 | 187, 0 | 189, 0 |

Per host, `lockfile_conflict` fired on 6, 8, 5 and 8 of 10 (requests, click, fzf, express) in
run-11 and run-12, and on 8, 6, 8 and 7 in run-13. Every other block fired on 10 of 10.

Every count was re-derived through a second path that does not use the library's matchers. It
rebuilt each state, evaluated every admitted program's preconditions directly, and graded each
program that held against the acceptable set read from the observed state. It counted a fire as
wrong if any program that held belonged to another fault or named a resolution outside that set,
which is stricter than grading the first. It agrees on all 60 blocks: the same fire counts, no
wrong fire, and no program holding on any fault-free state.

**The misses are paired, seed for seed.** The `lockfile_conflict` positives arm 3 sits out on the
real base are exactly the seeds it sits out on the synthetic base
(`results/abstentions-2026-10-12/run-N/abstentions.jsonl`): 13, 13 and 11 seeds, with none
missed on one base and fired on the other.

## What it shows

**The real base changed nothing measured.** Each library fires on the same number of positives
as on the synthetic base, every fire is correct, and none fires on a fault-free state. Every
positive arm 3 sits out is a `lockfile_conflict` state at a seed it also sits out on the synthetic
base. On these hosts, what arm 3 does at a seed did not depend on the history under the fault.

**One real interaction.** fzf's `.gitignore` ignores `vendor`, where `submodule_moved` puts its
submodule. The injector now adds it with `--force`, as a project with such a submodule must have.
The programs then fired on all 30 of fzf's `submodule_moved` positives, none wrong.

## What it does not show

- **A comparison with arm 2.** No held-out floor is measured, so no sentence may say arm 3 beats
  text similarity here (ADR-0033).
- **Real faults.** The base is real; the dirty files, the divergence, the lock file and the
  submodule are still the generator's.
- **Repositories in general.** Four small, well-kept projects are not a sample of repositories.
- **Episodes.** Only dispatch is measured. Whether a fired program's body then works on a real
  tree (an `add` of an ignored path needs `--force`, for one) is an episode-level question.
