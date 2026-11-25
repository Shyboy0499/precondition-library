# lockmerge on 895 real lock-file conflicts, 2026-11-25

`lockmerge` ([`lockmerge/`](../../lockmerge/README.md)) is a git merge driver for `package-lock.json`
and `composer.lock`. It merges a lock file record by record and refuses when a package was
changed differently on both sides, or when the merge would break a dependency requirement. This
folder replays every such conflict this project has mined through it, and grades each automatic
merge against what the maintainer committed.

**Exploratory, and a development set.** Nothing here was registered. Three of the tool's rules
were set while looking at these results:

- one package version recorded two ways merges;
- a Composer package that another replaces or provides counts as present;
- a merge never leaves the project's own requirements broken.

So these figures describe the data the tool was tuned on. A test on repositories it has not
seen is the next step (see "What it does not show").

```bash
PYTHONPATH=src:lockmerge/src python results/lockmerge-2026-11-25/evaluate.py --cache DIR
```

The script fetches each case's four versions (merge base, both parents, the maintainer's merge)
from `raw.githubusercontent.com` by commit. Only the commits and the derived grades are
committed here, as for every study.

## Cases

The cases are every positive case of studies 1, 3, 4, 5 and 6 whose conflicted files include a
supported lock file, deduplicated by repository, merge and path. That gives 897 conflicts from
68 repositories. Two maintainers deleted the file, which leaves **895 graded**: 374
`package-lock.json` from 45 repositories and 521 `composer.lock` from 44.

## Two modes

- **driver:** what `git merge` gives the driver, the lock file's three versions and nothing else.
- **resolve:** `lockmerge resolve`, run after `composer.json` is merged. Composer's
  `content-hash` is a fingerprint of `composer.json`, so when both sides changed `composer.json`
  only the merged one can supply it. The maintainer's committed `composer.json` stands in for
  the user's merge of it. For npm the two modes are the same.

## Result

| | merged automatically | valid for the merged manifest | same packages as the maintainer |
| --- | --- | --- | --- |
| `package-lock.json`, driver | 63 / 374 (0.168) | 60 / 63 | 45 / 63 |
| `composer.lock`, driver | 15 / 521 (0.029) | 14 / 15 | 12 / 15 |
| `composer.lock`, resolve | 187 / 521 (0.359) | 175 / 187 | 140 / 187 |

**What "valid" checks.** It runs offline, by the package manager's rules, on the maintainer's
merged manifest.

- **npm (as `npm ci` checks):** every dependency in `package.json` is locked, at a version in
  its range.
- **Composer:** the `content-hash` is the merged `composer.json`'s, and every requirement is met.

**The check is calibrated** on the maintainers' own committed files.

- 340 of 374 npm files pass it.
- 394 of 521 Composer files pass it. Of the 127 that fail, 125 carry a stale `content-hash`.
- The Python `content-hash` equals Composer's own PHP algorithm on all 521 real `composer.json`
  files.

**Every invalid automatic merge is a case whose maintainer's file is invalid too:** 3 npm and 1
plus 12 Composer. In no case did lockmerge produce an invalid file where the maintainer's was
valid.

**Why it declined.**

- **npm (311):**
  - 289: a package changed differently on both sides;
  - 3: a requirement would break;
  - 19: the two sides use different lockfile formats (one side upgraded npm).
- **Composer:**
  - 331: a package changed differently on both sides;
  - 174 in driver mode only: both sides changed `composer.json`, which `resolve` then settles;
  - 1–3: a requirement would break.

**Where it differs from the maintainer (18 npm, 47 Composer):**

- **27 cases:** the maintainer added versions neither side had, from re-running the package
  manager.
- **38 cases:** the maintainer dropped one side's change. Taking one side whole is common:
  "take ours" gives the maintainer's package set in 157 of 374 npm conflicts and 239 of 521
  Composer ones.

lockmerge keeps both sides' changes. Its merge differs from the maintainer's, and is valid for
the same manifest.

## What it shows

- **When it merges, the result is almost always installable.**
  - npm: 60 of 63 valid.
  - Composer: 175 of 187 valid.
  - Every exception had a manifest that was already inconsistent.
- **It merges a minority of conflicts.**
  - About 1 in 6 npm conflicts and 1 in 3 Composer ones.
  - Most lock-file conflicts have a package moved to two different versions, often by two
    dependency-bot updates. No file merge can settle those, and the tool names each one.
  - This matches studies 3–5: a merge computed from the sides covers part of the conflicts, and
    the rest needs the package manager or a person.

## What it does not show

- **Performance on repositories it was not tuned on.** The rules above were adjusted on this
  set. A held-out test means mining conflicts from repositories none of the studies used.
- **`--regenerate`.** Starting from ours and letting npm or Composer reconcile it with the
  merged manifest reaches today's registry, not the one of each merge's date. Replaying it on
  old merges would grade registry drift as error. That is study 3's caveat about regeneration.
- **Other lock files.** `yarn.lock`, `pnpm-lock.yaml`, `Gemfile.lock` and the rest are not
  supported yet.

## Files

- `evaluate.py`: the replay and grading.
- `cases.jsonl`: one row per conflict: the commits, the outcome in each mode, the reasons for a
  refusal, and each grade.
- `summary.txt`: the figures above.
