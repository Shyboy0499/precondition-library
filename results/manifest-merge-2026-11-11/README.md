# Can a resolver merge the manifests itself? 2026-11-11

**Exploratory.** This follows `results/manifest-leak-2026-11-11/`. That audit found the
ecosystem's check reading the maintainer's resolved manifests on 380 of the 1,005 lock files of
studies 3–6, because git reported a conflict in a file the check reads. A resolver at merge time
has no manifest there.

But manifests are package maps, as lock files are. So a resolver could merge them first, key by
key, and then run the check. This asks how often that gives exactly the maintainer's manifest.
Where it does, the recorded verdict is the one that resolver would get, so it is legitimate to
use, and no tool needs to be run again.

## Method

`merge.py` merges each conflicted `package.json` and `composer.json` three ways, key by key:
- a key both sides changed to different values is a conflict;
- anything else takes the side that changed it.

It compares the result with the maintainer's committed file as parsed JSON. Key order is aside;
the consistency checks ignore it. For npm and pnpm the root manifest's own `version` is set aside
first, because their checks ignore it. That was tested with a one-dependency project:
- **Changing only the root `version`:** `npm ci --dry-run` (npm 10.9.4) still passes, and so
  does `pnpm install --frozen-lockfile --lockfile-only` (pnpm 10.28.0).
- **Changing the dependency's range:** both refuse, with npm's "in sync" error and
  `ERR_PNPM_OUTDATED_LOCKFILE`.

A workspace package's `version` is not set aside.

Each of the 380 files gets one class (`classes.jsonl`):

| class | meaning | study 6 | studies 3–5 |
| --- | --- | ---: | ---: |
| **recovered** | the key-level merge gives the maintainer's manifests, and every other file the check reads is git's merge | 52 | 113 |
| **differs** | it merges, but to something else; the check's verdicts there were never computed | 25 | 21 |
| **unmerged** | a key changed on both sides, or a conflicted file is not a JSON manifest | 73 | 96 |

Where the merge fails, the clash is in (all studies, `classes.jsonl`'s `clash`):
- **a dependency map in 124 of the 169:** `dependencies`, `devDependencies`, `require`,
  `require-dev`, and once `optionalDependencies`;
- **pnpm's `packageManager` in 22**, which changes which pnpm runs, so it cannot be set aside;
- **other fields in 23:** `scripts` in 11, a workspace package's `version` in 6, and a few
  more.

## Result

How often the side the check accepts is wrong, by class:

| | conflicted, not recovered | recovered | same (git's merge) |
| --- | ---: | ---: | ---: |
| study 6 | 6 of 56 | 3 of 14 | 27 of 88 |
| studies 3–5 | 11 of 56 | 8 of 48 | 75 of 179 |

**D''** is the gate's merge; else the side the check accepts, where the check reads git's merge
or a recovered manifest; else refuse.

| rule | study 6: coverage | mismatch [95% Wilson] | studies 3–5: coverage | mismatch |
| --- | ---: | --- | ---: | --- |
| B: the gate's merge, else refuse | 0.45 | 0.296 [0.234, 0.367] | 0.40 | 0.279 [0.227, 0.338] |
| D, as recorded | 0.71 | 0.272 [0.224, 0.327] | 0.69 | 0.317 [0.274, 0.363] |
| D': the check on git's merge only | 0.58 | 0.299 [0.243, 0.361] | 0.58 | 0.343 [0.295, 0.394] |
| **D'': and on recovered manifests** | **0.60** | **0.304** [0.249, 0.365] | **0.61** | **0.336** [0.290, 0.385] |

Study 6's per-repository mean of D'' is 0.330 [0.240, 0.421].

What this says:
- **The check is accurate where both sides changed the manifest, and that is not the leak.** On
  recovered files the resolver legitimately has the maintainer's manifest. There the check is
  wrong on 3 of 14 and 8 of 48, close to the conflicted files and far from the "same" ones. So
  the gap between classes in `manifest-leak` is mostly a difference between kinds of conflict.
  When both sides changed dependencies, one side's lock file usually fails the merged manifest
  and the other's does not.
- **Merging the manifests first recovers little coverage.** D'' fires on 6 more files than D'
  in study 6, and 19 more in studies 3–5. Most recovered files have no divergent package, so the
  gate already fires there, or the check does not accept exactly one side.
- **The coverage rule D lost mostly needs the maintainer's own decision about dependencies.**
  There are 42 tie-break files D fires on and D'' cannot in study 6, and 51 in studies 3–5:
  - on 27 and 31 of them, both sides edited the same entry of a dependency map;
  - on 0 and 13, pnpm's `packageManager`;
  - 7 and 6 merge, but to another manifest;
  - the rest are scripts, other fields, a file that is not valid JSON, and one edited by the
    maintainer.

  Choosing between two edits of a dependency is resolving the conflict. This is the report
  taxonomy's "decision outside the lock file", now located in the manifest.

## Files

- `merge.py`: the key-level merge and the classes, from `audit.py`'s cache of each case's four
  commits. It writes `classes.jsonl`: per conflicted lock file, the class, the number of
  conflicted files the check reads, the top-level section of a clash, and whether the root
  `version` was set aside. No package name or other path is written.
- `analyze.py`: rules B, D, D' and D'', from `manifest-leak-2026-11-11/analyze.py`'s records,
  into `summary.txt`. It imports nothing from the project.

```bash
cd results/manifest-merge-2026-11-11
python -I merge.py <audit.py's cache> > classes.jsonl
python -I analyze.py > summary.txt
```
