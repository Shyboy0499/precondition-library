# What maintainers did where no computed action reproduces them, 2026-11-02

**Exploratory.** This runs on studies 3 and 4's committed labels, which have been seen, and
tests nothing. It describes the conflicts the lock-file oracle cannot label: 124 unreproduced
conflicted files in study 3 and 67 in study 4. That shapes what a next registration could add.

```bash
PYTHONPATH=src python results/lock-uncovered-2026-11-02/uncovered.py <study> <its real-hosts cache>
PYTHONPATH=src python results/lock-uncovered-2026-11-02/recombine.py <study> <its real-hosts cache>
```

Both scripts re-read the files from git at the studies' SHAs, with `bench.lock_actions` as fixed
on 2026-11-02 (deterministic `unify`). Their outputs are `study-3.txt` and `study-4.txt`.

## Two kinds of miss

| | study 3 | study 4 |
| --- | ---: | ---: |
| unreproduced conflicted files | 124 | 67 |
| **new resolution**: the maintainer's set holds a version that none of base, local or upstream had | 63 (51%) | 12 (18%) |
| **recombination**: only versions the sides had, but not the selection any action makes | 61 (49%) | 55 (82%) |
| median share of the maintainer's set that is new, for new resolutions | 6.2% | 0.7% |

- **A new resolution needs a resolver.** No computed action can produce a version nobody had. In
  these files the maintainer ran a resolver: they regenerated, updated, or added a dependency in
  the merge itself. In study 3 these were mostly composer, Gemfile and poetry files.
- **A recombination is a near-miss of the merge.** The maintainer's set differs from the
  per-ecosystem three-way merge (plain for npm's family, unified otherwise) by a median of 2
  pairs in study 3 and 1 in study 4.

## How recombinations differ from the merge

| the maintainer's set, against the merge | study 3 | study 4 |
| --- | ---: | ---: |
| left out one side's change (an addition or bump) | 21 | 21 |
| left out a side's change **and** kept the base version instead | 16 | 14 |
| kept a base version a side had changed | 8 | 12 |
| removed a package both sides kept | 10 | 3 |
| other combinations | 5 | 5 |
| equals the merge once `unify` breaks ties deterministically | 1 | 0 |

The commonest pattern is that the maintainer **did not take some side's change** to a package:
they dropped it, or kept the base version. That covers 50 of study 3's 61 recombinations (82%)
and 52 of study 4's 55 (95%).

That is what happens when the merged *manifest* no longer asks for the change. A maintainer who
resolves `composer.json` or `package.json` by keeping one side's constraint, then lets the tool
settle the lock file, drops the other side's bump. A package-level merge that sees only lock
files cannot know.

The single study-3 file whose verdict is set by `unify`'s tie-break is one of the two snipe-it
cases named in `results/lock-oracle-2026-11-02/README.md`.

## What it suggests, untested

- **A manifest-aware merge.** It would restrict the three-way merge to what the maintainer's
  merged manifests still require, and keep the base version where they pin it. That could cover
  much of the recombination share, without a registry, because the manifests are in the merge.
  It is a candidate for a registered study 5 on fresh repositories.
- **A new resolution is the oracle's honest limit.** A computed action cannot be expected to
  match it. For a dispatcher those are cases to refuse, or to hand to the ecosystem's tool, as
  #297 proposes.
