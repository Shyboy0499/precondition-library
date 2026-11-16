# Lock files at paths no build or held-out state used, on 25 libraries, 2026-11-16

`results/heldout-2026-11-16/` found build 0-4's `diverged` merge program firing on 20 lock-file
conflicts. Its check `no_common_lockfile_changes` knows lock files only by a fixed list of names,
so it sees no lock file named `abhängigkeiten.lock` or `.deps.lock`, holds, and the merge fires.

This folder asks two follow-up questions:

1. Do other libraries carry the same kind of check?
2. Would a build-time test that moves the lock file to an unseen path have refused 0-4's program?
   What else would it have refused?

**Exploratory.** Nothing here was registered. No model call, no rebuild: committed libraries are
read, and each library's digest is checked unchanged afterwards.

```bash
python results/lock-path-perturbation-2026-11-16/scan.py > scan.json
PYTHONPATH=src python results/lock-path-perturbation-2026-11-16/perturb.py > perturb.json
```

## 1. Which checks know lock files by a list of names (`scan.py`)

`scan.py` reads every precondition of every committed library: 47 library folders, two-sided and
positive-only. It lists each probe that names two or more common lock files. It also records whether
the probe accepts any name ending in `.lock` as well: a glob `*.lock`, a pattern `[^/]*\.lock`, or a
Python suffix test.

| library | program | precondition | kind | also any `*.lock` |
| --- | --- | --- | --- | --- |
| 0-4 | `diverged` merge | `no_common_lockfile_changes` | absence: holds if no shared lock file | **no** |
| R-7 | `diverged` merge | `no_lockfile_changed_on_both_sides` | absence | yes |
| 0-1 | `lockfile_conflict` | three checks | presence (two), absence over lock files (one) | yes |
| 0-8 | `lockfile_conflict` | two checks | presence | yes |
| R-4 | `lockfile_conflict` | `dependency_file_collision` | presence (both libraries) | yes |

The kind column is from reading each probe in `scan.json`.

- **A presence check fails closed on a name it does not know.** It requires a lock file, finds
  none, and refuses.
- **An absence check fails open.** It requires that there be no lock file, finds none, and holds.

Of the nine checks, 0-4's is the only one with no `*.lock` rule. Two absence checks guard a merge
program: 0-4's and R-7's. R-7's knows any `*.lock` name, which is why the held-out paths, all
ending in `.lock`, never caught it.

## 2. A build-time test at unseen paths (`perturb.py`)

**The states.** `perturb.py` builds the `lockfile_conflict` fault at three shipped seeds, one per
live state (0, 2 and 5). It moves the lock file to six paths no shipped or held-out state uses:

- four ending in `.lock`: `lib/Zuordnung.lock` (an unseen ASCII name), `lib/Übersicht.lock`
  (non-ASCII), `deps/.packages.lock` (a dotfile), `tools/build cache/state.lock` (a space);
- two that do not: `deps-lock.txt`, `packages.lockfile`.

**The libraries.** Every committed two-sided library, 25 in all:

- study 2's 20;
- run-14 and run-15;
- October's run-11 to run-13, compiled before the prompt told the model to read path lists with
  `-z`.

**What counts as a refusal.** Every admitted program's preconditions run on each of the 18 states.
Admission's two-sided rule requires a program compiled for another fault to refuse a state of this
one. So a non-`lockfile_conflict` program that fires here is one such a test would have refused.

| library | program that fires on another family's state | paths it fires at | fires |
| --- | --- | --- | --- |
| 0-4 | `diverged-occ1-diverged-fork-sync-merge` | all six | 18 of 18 |
| R-7 | `diverged-occ5-diverged-sync-merge-preserve-history` | `deps-lock.txt`, `packages.lockfile` | 6 of 18 |
| run-11 | `diverged-occ1-diverged-local-only-additions-discard` | `lib/Übersicht.lock` | 3 of 18 |
| run-13 | `diverged-occ1-sync-fork-discard` | `lib/Übersicht.lock`, `tools/build cache/state.lock` | 6 of 18 |
| all 25 | any other program | none | 0 |

The `lockfile_conflict` programs' own fires (194) are in `perturb.json` and are not counted here.
The other 20 libraries built since the prompt change have no program in the table.

## What it shows

- **Such a test would have refused 0-4's program at build time, at every unseen path tried.**
- **It finds one more program of the same kind, which no held-out path could reach.** R-7's
  absence check accepts any `*.lock` name. It goes blind only when the lock file's name does not
  end in `.lock`, and every held-out path ends in `.lock`.
- **It re-finds October's two `diverged` defects, at paths October did not use.** Both were found
  by `results/heldout-2026-10-18/`, so they check the test rather than add a finding:
  - run-11's `local_commits_touch_no_path_upstream_carries` reads the escaped name git prints for
    a non-ASCII path, so it fires at `lib/Übersicht.lock` only.
  - run-13's `local_commits_carry_nothing_new` passes an unquoted `$files` to `git diff -- $files`.
    It fires at the path with a space, which splits into pathspecs that match nothing, and at the
    non-ASCII path, which git prints escaped. Either way the diff is empty and the check holds.
- **Of the 22 libraries built since the prompt change, two programs fire: 0-4's and R-7's.**
  Neither fires because of a misread path; both know lock files by name.
- **It costs no other program.** Every other program of the 25 libraries refuses all 18 states.

## What it does not show

- **That the test should be added to admission.** It would change the method for future builds.
  That needs a decision record, and its paths must stay disjoint from the held-out block's, or the
  held-out test stops being held out. Study 2's builds are frozen and unaffected either way.
- **That the four programs' fires would be graded wrong.** No grader ran. The count is of
  two-sided admission violations: another family's program firing on this family's state. In the
  held-out block, every one of 0-4's fires of this kind was graded wrong.
- **Anything about other kinds of unseen state.** Only the lock file's path and name vary.
- **That six paths are enough.** Each defect above shows only at the paths that break it. The
  first run of this script used five paths, none non-ASCII, and missed run-11's.

## Files

- `scan.py` and `scan.json`: the closed-list scan, with each matching probe's text.
- `perturb.py` and `perturb.json`: the paths, seeds, libraries and every fire.
