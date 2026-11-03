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
- **All 8 failures are glpi's.** Eight of its nine files fail from both sides. The pilot did not
  record npm's error output, so the cause is not known. It may be a peer-dependency conflict
  (`ERESOLVE`), which `--legacy-peer-deps` would bypass, but that is a guess.

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
