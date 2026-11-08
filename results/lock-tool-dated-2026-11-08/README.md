# pnpm and Composer, held to the merge's date, on the conflicts the computed oracle missed, 2026-11-08 (#336)

**Exploratory.** This runs on studies 3, 4 and 5's data, which have been seen, and tests nothing.
It follows the npm pilot (`results/lock-tool-dated-2026-11-03/`) to the next two ecosystems the
computed oracle misses most. It was run with the owner's approval of date-pinned pnpm and of
Composer plugins.

## Which ecosystems can be held to a date

| ecosystem | how | status |
| --- | --- | --- |
| npm | `npm install --before=<date>` | piloted on 2026-11-03: 14 of 52 files reproduced |
| pnpm | `minimumReleaseAge` (pnpm 10.16+, in minutes) | **piloted here** |
| Composer | no option; the `cotonet/soak-time` plugin drops versions younger than `extra.soak-time-hours` | **piloted here** |
| uv | `--exclude-newer=<date>` | no `uv.lock` is among studies 3–5's unreproduced files |
| Bundler | no option; the `bundler-as_of` plugin | **unusable**, see below |
| Cargo, Poetry | no option found | not run |

**Why `bundler-as_of` cannot be used.** Its source shows that it acts on `bundle install`, not on
resolution alone. It then replaces every dependency with its latest version as of the date,
whatever the lock file holds. So it cannot start from a side's lock file, and a run installs gems,
which builds native extensions and so runs their code.

## The method

Each conflicted `pnpm-lock.yaml` and `composer.lock` that no computed action reproduced is
used: 20 pnpm files and 84 Composer files across the three studies. For each one:

1. The merge's whole tree, as committed (`lock_actions._checkout`; see
   `results/archive-attributes-2026-11-08/`).
2. One side's lock file, put in place of the maintainer's.
3. The tool, refusing versions released after the merge:
   - **pnpm:** `pnpm install --lockfile-only --ignore-scripts --no-frozen-lockfile` with
     `minimumReleaseAge` set to the minutes since the merge. The pnpm is the version the merged
     `package.json` declares, which was 10.31 to 12.16 here; with none declared, it is 10.28.
   - **Composer:** Composer's documented way to settle a conflicted `composer.lock`. It takes one
     side's lock file and updates the root requirements whose constraint differs from the
     merged `composer.json`: `composer update --no-install --no-scripts -W --minimal-changes
     <packages>`. With none to update, the side's lock file is the answer. The plugin's age is
     the whole hours since the merge, and packages the lock pins to a branch are exempt from it.
4. The result's `(package, version)` set, compared with the maintainer's.

Neither tool installs or runs any package's code. Composer 2.8.12, Node 22.22.

**The sanity run** puts the maintainer's own merged lock file in, and should get it back. It
measures whether the tool can replay that merge's resolution here at all.

```bash
PYTHONPATH=src python results/lock-tool-dated-2026-11-08/tool_dated.py <study> <cache> <scratch> composer [--sanity]
PYTHONPATH=src python results/lock-tool-dated-2026-11-08/tool_dated.py <study> <cache> <scratch> pnpm [--sanity]
python -I results/lock-tool-dated-2026-11-08/summary.py results/lock-tool-dated-2026-11-08
```

Composer needs `COMPOSER_HOME` to hold the plugin, installed with
`composer global require cotonet/soak-time`. The logs (`study-*.{composer,pnpm}[.sanity].log`)
give every file's outcome, and `summary.txt` their tables.

## Result

| | Composer | pnpm |
| --- | ---: | ---: |
| unreproduced files | 84 | 20 |
| **sanity:** the tool replays the maintainer's own lock file exactly | 54 | 18 |
| **from a side:** the tool reproduces the maintainer's set, from one side or the other | **11** | **5** |
| of them, among the files that passed the sanity run | **9 of 54 (17%)** | **5 of 18** |
| near only (a run succeeded, but no exact match): median best Jaccard | 67 files, 0.882 | 6 files, 0.996 |
| failed from every side | 6 | 9 |

### What the sanity run shows

**Composer cannot replay a third of its own merges** (30 of 84 fail or differ).

- **Branch dependencies cause most of it**, 18 of the 26 failures. A package pinned to `dev-main`
  or `2.x-dev` is served by Packagist only at the branch's current head. The head's requirements
  have moved since the merge, so the old resolution no longer loads.
- The rest:
  - five resolutions no longer resolve with today's metadata for the date's versions;
  - two Composer errors on old lock files;
  - `humhub/humhub`, which needs asset-packagist.org, a host the network policy blocks.

**pnpm replays 18 of 20.** One element-web file gets Jaccard 0.998. The failure is
`rust-lang/crates.io`, whose declared pnpm is older than `minimumReleaseAge`, so pnpm 10.28 refuses
it.

### What the runs from each side show

- **Composer rarely reproduces a maintainer's lock file this way: 9 of the 54 it can replay.** The
  common reason shows in the logs. On 57 sides, the side's lock file already satisfies the merged
  `composer.json`, so Composer's procedure has nothing to update, and still the maintainer's file
  differs. The maintainer changed more than the manifests required, as a broader `composer update`
  would. No replay that starts from the manifests recovers that.
- **pnpm reproduces 5 of the 11 files it could run from a side.** All five are `penpot/penpot`, from
  its first side. The other runs are close, at a median best Jaccard of 0.996. But 17 side runs fail
  on one cause: element-web and penpot depend on git tarballs from codeload.github.com, which the
  network policy blocks. Eight pnpm files could not be run at all.

## What it shows, and what it does not

- **Across the three ecosystems, the dated tool recovers a fifth of the computed oracle's
  misses.** Over every unreproduced file, that is 30 of 156: npm 14 of 52, Composer 11 of 84,
  pnpm 5 of 20. Over only the files the tool could run, it is a quarter (28 of 117): Composer 9
  of the 54 it can replay, pnpm 5 of the 11 it could run from a side. That is too little to
  label conflicts with, and it is uneven: pnpm's five are one repository's.
- **The decision #336 asks for:** no labelling study is registered on the dated tool now. A
  registration would need pnpm's git-tarball host allowed and more than one pnpm repository.
  For Composer, the maintainers' broader updates bound what any replay can recover.
- **It tests nothing.** The files were chosen by having been missed, after the data was seen.

## Limits

- **Release dates are the registry's.** Composer's plugin dates a version by its release date,
  which Packagist takes from the tag and a tag can carry any date. The age is in whole hours,
  rounded down, so up to an hour after the merge is admitted.
- **The tool versions differ from the maintainers'.** pnpm is the declared version. Composer is
  2.8.12 whatever the maintainer used. PHP is this container's 8.3 unless that alone fails, when
  platform requirements are ignored (marked "(php ignored)" in the logs).
- **A repository's own `minimumReleaseAgeExclude` still applies** to pnpm, so packages it lists
  are not held to the date.
