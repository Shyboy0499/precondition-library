# The anatomy of a lock-file conflict, 2026-11-04

**Exploratory.** This reads studies 3 and 4's conflicted lock files, which have been seen, and
tests nothing. It asks two things the registered studies did not:

- **Why** a merge computed from the three sides reproduces the maintainer when it does, and
  fails when it fails.
- **What a dispatcher could actually do with it.** Coverage counts a conflict as labelled when
  *any* of four actions reproduces it. A dispatcher has to pick one action without seeing the
  maintainer's answer.

```bash
PYTHONPATH=src python results/lock-anatomy-2026-11-04/anatomy.py <study> <real-hosts> <out.jsonl>
python results/lock-anatomy-2026-11-04/summary.py \
    results/lock-oracle-2026-11-02 results/lock-anatomy-2026-11-04/study-3.jsonl \
    results/ecosystem-unify-2026-11-02 results/lock-anatomy-2026-11-04/study-4.jsonl
```

`anatomy.py` re-reads every conflicted file from git at the studies' SHAs. It writes one line per
file to `study-3.jsonl` and `study-4.jsonl`. `summary.py` combines those lines with the registered
labels, and its output is `summary.txt`. The report's tables `anatomy.tex` and `rules.tex` are
generated from the same files by `paper/analysis/tables.py`. That script checks every file
against the registered labels.

The merge recomputed here agrees with the registered label on every file except two. Those two
are the snipe-it files whose verdict depends on `unify`'s tie-break
(`results/lock-oracle-2026-11-02/README.md`).

## A line conflict is usually not a package conflict

Each package name in a conflicted file falls into one kind:

| kind | meaning |
| --- | --- |
| untouched | neither side changed its versions |
| one-sided | exactly one side changed them: added, removed or moved the package |
| convergent | both sides changed them, to the same versions |
| **divergent** | both sides changed them, to different versions |

Only divergent names lack a single answer that a three-way merge computes. They are a conflict at
the level of packages, and they are rare:

| | study 3 | study 4 |
| --- | ---: | ---: |
| conflicted files | 412 | 290 |
| files with no divergent package | 200 (49%) | 162 (56%) |
| package names, all files: one-sided | 40,179 | 37,588 |
| package names, all files: divergent | 2,240 | 1,330 |

So half of the conflicts git reports in a lock file are not conflicts between the two sides'
package choices at all. They are the line format colliding. Two sides that each add or bump
different packages touch neighbouring lines of the file, so git cannot merge them.

## Divergence decides whether the merge works

The table shows, for each count of divergent packages, the conflicted files and the share the
predicted per-ecosystem merge reproduces.

| family | divergent | study 3 files | reproduced | study 4 files | reproduced |
| --- | --- | ---: | ---: | ---: | ---: |
| npm's | 0 | 59 | 0.66 | 73 | 0.82 |
| | 1 | 25 | 0.04 | 33 | 0.12 |
| | 2–4 | 25 | 0.08 | 16 | 0.00 |
| | 5+ | 44 | 0.05 | 24 | 0.12 |
| one-version | 0 | 141 | 0.68 | 89 | 0.73 |
| | 1 | 45 | 0.42 | 26 | 0.65 |
| | 2–4 | 32 | 0.22 | 15 | 0.40 |
| | 5+ | 41 | 0.15 | 14 | 0.14 |

The predicted merge is the unified one for the one-version family and the plain one for npm's,
as study 4 registered.

- **In npm's family, a single divergent package almost always defeats the merge.** The plain
  merge keeps both sides' versions of the package, and maintainers almost never do.
- **In the one-version family, the merge degrades gradually.** Unifying keeps the highest
  version, which is often what the maintainer kept.

## What maintainers kept where packages diverge

This counts files with a divergent package by what the maintainer kept on all of that file's
divergent packages:

| | study 3 npm | study 3 one-version | study 4 npm | study 4 one-version |
| --- | ---: | ---: | ---: | ---: |
| local's versions on all of them | 46 | 52 | 26 | 29 |
| upstream's on all of them | 17 | 22 | 16 | 13 |
| mixed, or something else | 31 | 44 | 31 | 13 |

"Local" is the first parent: the branch the maintainer was on when they merged. Where the two
sides disagree, maintainers keep their own side about twice as often as the incoming one.

The next table looks only at those same files. "Right outside the divergent packages" counts
files where the merge matches the maintainer on every other package, so the right versions on
the divergent ones would reproduce the file. Each tie-break column counts files that the merge
reproduces when it settles each divergent package by that rule.

| files with a divergent package | study 3 npm | study 3 one-version | study 4 npm | study 4 one-version |
| --- | ---: | ---: | ---: | ---: |
| files | 94 | 118 | 73 | 55 |
| the predicted merge reproduces | 5 | 32 | 7 | 25 |
| right outside the divergent packages | 39 | 61 | 37 | 39 |
| local's version wins | 26 | 33 | 20 | 29 |
| upstream's wins | 7 | 16 | 9 | 10 |
| the highest wins | 17 | 36 | 11 | 24 |

## Why the merge misses where nothing diverges

The predicted merge misses 65 files in study 3 and 37 in study 4 where no package diverges. The
reasons overlap:

| | study 3 | study 4 |
| --- | ---: | ---: |
| a one-sided change the maintainer did not take | 52 | 36 |
| a version no side had: the maintainer ran a resolver | 23 | 4 |
| a package neither side touched, changed in the merge | 16 | 4 |

This is the manifest effect `results/lock-uncovered-2026-11-02/` describes. The maintainer
resolved the manifest by keeping one side's constraint, and the lock file followed.

## By repository

Repositories differ widely. Registered coverage runs from 0.27 to 1.0 in both studies. The share
of a repository's cases with a divergent package explains part of that spread in study 4
(Spearman ρ −0.65 over 20 repositories) and little in study 3 (ρ −0.13 over 27). In study 3, the
repositories with low coverage despite little divergence are mostly ones where maintainers ran a
resolver. rust-lang/crates.io is the clearest: divergence 0.13, coverage 0.27.

## From an oracle to a dispatcher

The registered coverage, 0.686 and 0.760, is an oracle's figure. A case is labelled if any of
four actions reproduces it, and choosing among them needs the answer. The table below scores
rules that read only the three sides, case by case: wrong fires over fires, then mismatch with
its 95% Wilson interval.

| rule | study 3 | | study 4 | |
| --- | ---: | ---: | ---: | ---: |
| the merge, always | 203/360 | 0.56 [0.51, 0.61] | 119/266 | 0.45 [0.39, 0.51] |
| the merge, local's version where a package diverges | 188/360 | 0.52 [0.47, 0.57] | 107/266 | 0.40 [0.35, 0.46] |
| the merge if no package diverges, else `take_local` | 162/360 | 0.45 [0.40, 0.50] | 102/266 | 0.38 [0.33, 0.44] |
| **the merge if no package diverges, else refuse** | **64/197** | **0.32 [0.26, 0.39]** | **33/151** | **0.22 [0.16, 0.29]** |
| `take_local`, always | 259/360 | 0.72 [0.67, 0.76] | 163/266 | 0.61 [0.55, 0.67] |

- **"No package diverges" is an executable precondition.** It is computed from the three sides
  alone, and it is exactly the kind of check this project compiles. Firing only when it holds
  cuts the merge's mismatch by about 40–50%, while still firing on 55–57% of conflicts.
- **It is still far from rarely wrong.** Its interval sits well above study 1's rule-2 bound of
  0.10. What remains is mostly the manifest effect above, which no check over the lock files
  can see.

## Where each conflicted `package-lock.json` ends up

Combining this with `results/lock-tool-dated-2026-11-03/` (run with `--engine-strict=false`)
gives, for the 172 conflicted `package-lock.json` files of both studies:

| stage | files labelled | cumulative |
| --- | ---: | ---: |
| some computed action reproduces it | 120 | 120 (0.70) |
| npm, pinned to the merge's date, reproduces it | 14 | 134 (0.78) |
| neither | 38 | — |

## Limits

- **All of this was chosen after seeing the data.** That covers the tie-break rules, the
  divergence precondition and the thresholds in the tables. A registration on fresh repositories
  would have to fix the rule before mining. The candidate is "the merge if no package diverges,
  else refuse", with its mismatch bound stated in advance.
- **A name stands for every copy of a package.** `lock_actions` reads npm's nested copies
  (`node_modules/a/node_modules/b`) under the package's own name. So in npm's family a name's
  versions are the set of all its copies' versions, and a change to one nested copy counts as a
  change to the package. Names are compared exactly, case included.
