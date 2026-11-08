# npm, pinned to the merge's date, on the conflicts the computed oracle missed, 2026-11-03 (#336)

**Exploratory.** This runs on studies 3 and 4's data, which have been seen, and tests nothing.
It is the pilot #336 asks for, run with the owner's approval.

For every conflicted `package-lock.json` that no computed action reproduced (37 in study 3, 15
in study 4), it starts from each side's lock file in turn. It puts that file into the merge's
own tree and lets npm reconcile it against the merged `package.json`, using the registry as it
stood when the merge was committed:

```bash
npm install --package-lock-only --ignore-scripts --no-audit --no-fund --before=<merge's committer date>
```

- `--package-lock-only` resolves without installing anything.
- `--ignore-scripts` runs no package's code.
- `--before` makes the registry answer as it stood that day, so a resolution the maintainer
  made then can be replayed now.

The result's `(package, version)` set is compared with the maintainer's.

```bash
PYTHONPATH=src python results/lock-tool-dated-2026-11-03/npm_dated.py <study> <real-hosts> <scratch>
PYTHONPATH=src python results/lock-tool-dated-2026-11-03/kinds.py <study> <real-hosts> <its log>
```

`study-3.log` and `study-4.log` give every file's outcome from each side. `kinds.txt` splits
them by the kinds in `results/lock-uncovered-2026-11-02/`.

## Result

| | study 3 | study 4 | both |
| --- | ---: | ---: | ---: |
| unreproduced `package-lock.json` files | 37 | 15 | 52 |
| **npm reproduces the maintainer's set exactly**, from one side or the other | **12** | **1** | **13 (25%)** |
| npm fails from both sides | 0 | 8 | 8 |

| kind of miss | reproduced | near (not exact) | failed |
| --- | ---: | ---: | ---: |
| recombination: only the sides' versions | 10 of 31 | 17 | 4 |
| new resolution: a version none of the sides had | 3 of 21 | 14 | 4 |

- **A quarter of the computed oracle's npm misses have an answer the ecosystem's own tool
  reproduces exactly**, when pinned to the merge's date. Most of those are recombinations: 10 of
  31, against 3 of 21 new resolutions. So the dated tool recovers mainly the near-misses that a
  manifest-aware merge could not (#335).
- **The rest are near.** Where npm runs but does not reproduce, its result is usually close: for
  example Jaccard 0.98 on mautic and 0.995 on one of glpi's files, from one side. Some maintainers' lock files
  were evidently produced with a different npm version or options, or edited by hand.
- **All 8 failures are glpi's.** Eight of its ten files fail from both sides. The cause is the
  container's Node, not the resolver: see the addendum below.

## What it shows, and what it does not

- **The tool oracle works where the computed oracle cannot, for npm, at least sometimes.** Taken
  with studies 3 and 4, a labeller could use the per-ecosystem merge first, then the dated tool
  from either side. On these npm files that would label 13 more conflicts with the maintainer's
  exact resolution.
- **It is not tested.** These files were selected by having been missed, after seeing the data.
  A registration would fix the order of actions, the npm version and options, and the
  repositories, before mining.
- **Only npm.** Composer, bundler, poetry and cargo have no equivalent of `--before` in their
  CLIs. Replaying them needs a registry snapshot, which #336 lists as the open question.
- **The npm version matters.** This ran npm 10.9.4, whatever the maintainer used. The format
  versions differ, but the comparison is of package sets, so formats alone do not cause a
  mismatch.

## Addendum, the same day: the glpi failures were the engine check

The first run did not record npm's error output. Run by hand, every glpi failure is
`EBADENGINE`. glpi's `package.json` requires Node `>= 24.11`, and its `.npmrc` sets
`engine-strict=true`. This container has Node 22.22.0, so npm refuses to start.

The engine check guards installation, not resolution, so both studies were run again with
`--engine-strict=false` (`study-3.engine-strict-false.log`, `study-4.engine-strict-false.log`,
`kinds.engine-strict-false.txt`). `npm_dated.py` now passes options starting with `--` on to
npm and prints the code of any npm error.

```bash
PYTHONPATH=src python results/lock-tool-dated-2026-11-03/npm_dated.py <study> <real-hosts> <scratch> --engine-strict=false
```

| | study 3 | study 4 | both |
| --- | ---: | ---: | ---: |
| **npm reproduces the maintainer's set exactly**, from one side or the other | **12** | **2** | **14 of 52 (27%)** |
| npm fails from both sides | 0 | 0 | 0 |
| recombinations reproduced | 9 of 22 | 2 of 9 | 11 of 31 |
| new resolutions reproduced | 3 of 15 | 0 of 6 | 3 of 21 |

- **Study 3 is unchanged, file for file.** Its logs are identical apart from the error codes now
  printed.
- **Study 4 changes only on glpi.** All ten of its files now run. One more reproduces, a
  recombination (case 74, from the first side), and the other nine are near: Jaccard 0.94 to
  0.997 from the first side, 0.59 to 0.67 from the second.
- **The remaining single-side failures are loomio's.** Four are `ERESOLVE`, a peer-dependency
  conflict, from the second side; one is `E403` from the registry, from the first. Each of those
  files ran from the other side.
- **So the recovered share is 14 of 52, not 13**, with nothing failing outright. The conclusions
  above stand: npm recovers recombinations more often than new resolutions (11 of 31 against 3
  of 21).

## Addendum, 2026-11-08

- **pnpm and Composer were piloted the same way** (`results/lock-tool-dated-2026-11-08/`).
  pnpm has `minimumReleaseAge`, and Composer a plugin that drops versions younger than an age.
  Bundler's plugin turned out to be unusable.
- **The trees here were extracted with `git archive`**, which applies a repository's
  `export-ignore`. `results/archive-attributes-2026-11-08/` checked every merge this pilot ran
  npm in. Files were left out of 10 of them, but never a manifest, lock file or `.npmrc`, so no
  outcome here changes.
