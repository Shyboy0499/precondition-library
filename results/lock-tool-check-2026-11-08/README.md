# The ecosystem's own consistency check, beside the maintainer's merge, 2026-11-08 (#297)

**Exploratory.** This runs on studies 3, 4 and 5's conflicts, which have been seen, and tests
nothing. It is #297's second oracle. #297 asks for three:

- **the maintainer's merge.** Studies 3–5 read it at the package level: is a resolution the
  maintainer's `(package, version)` set?
- **the ecosystem's own lock-file check.** This is the one here.
- **the project's own tests.** These are not run. The owner declined running projects' test
  suites, which would execute the projects' code.

## What is checked

The tool can only judge a real lock file, so three are checked for every conflicted
`package-lock.json`, `pnpm-lock.yaml` and `composer.lock` of the three studies. Each is put into
the merge's tree as committed (`lock_actions._checkout`):

- **the maintainer's merged lock file**, as a control. The check should pass it.
- **the first parent's lock file**, study 3's `take_local`.
- **the second parent's**, `take_upstream`.

| tool | files | the check |
| --- | ---: | --- |
| npm | 204 | `npm ci --dry-run --ignore-scripts --engine-strict=false`: npm refuses (`EUSAGE`) when the lock file and `package.json` are out of sync |
| pnpm | 47 | `pnpm install --frozen-lockfile --lockfile-only --ignore-scripts` with the declared pnpm: it refuses when the lock file is outdated, or was written under other settings (overrides, patches, peer handling) |
| Composer | 359 | offline. `composer install --dry-run`: does the locked set satisfy every root requirement and install? It also checks the `content-hash` with `composer validate` |

None of the checks installs a package or runs a package's code. The Composer check runs with no
network at all. npm and pnpm read registry metadata: npm when the files are out of sync, and
pnpm 11+ always, to check locked versions against its release-age policy. So this is not the
offline mirror #297 imagined. Their verdict on consistency does not depend on the registry's
state.

```bash
PYTHONPATH=src python results/lock-tool-check-2026-11-08/check.py <study> <cache> <scratch> <out.jsonl>
PYTHONPATH=src python results/lock-tool-check-2026-11-08/own_trees.py <study> <cache> <scratch> <out.jsonl>
python -I results/lock-tool-check-2026-11-08/summary.py results/lock-tool-check-2026-11-08
python -I results/lock-tool-check-2026-11-08/own_summary.py results/lock-tool-check-2026-11-08
python -I results/lock-tool-check-2026-11-08/dispatch.py results/lock-tool-check-2026-11-08
```

| file | what it holds |
| --- | --- |
| `study-{3,4,5}.jsonl` | every file's three verdicts in the merge's tree, and whether each side is the maintainer's set |
| `study-{3,4,5}.own.jsonl` | each parent's and the merge base's lock file, checked in its own commit's tree |
| `summary.txt`, `own_summary.txt`, `dispatch.txt` | the tables below |

No package name is written anywhere.

## Result

### The control: the maintainers' own files

| tool | the check passes the maintainer's merged lock file | rejects it | fails to run |
| --- | ---: | ---: | ---: |
| npm | 174 of 204 (85%) | 26 | 4 (`ERESOLVE`) |
| pnpm | 37 of 47 | 5 | 5 |
| Composer | 305 of 359 (85%) | 54 | 0 |

- **One maintainer merge in seven is committed in a state the ecosystem's own check rejects.**
- **Composer's content-hash is staler still.** 104 of 359 merged files (29%) carry a hash that no
  longer matches their `composer.json`. Composer warns about a stale hash but still installs.

### Agreement: the tool against the maintainer, on each side's lock file

| tool | side is the maintainer's set: tool passes it | side is not: tool rejects it | runs that failed |
| --- | ---: | ---: | ---: |
| npm | 107 of 126 | 186 of 238 | 44 |
| pnpm | 15 of 20 | 65 of 68 | 6 |
| Composer | 166 of 203 | 360 of 514 | 1 |

Of pnpm's 65 rejections, 25 are for settings, not manifests: the side's lock file was written
under other overrides, patches or peer settings than the merge's.

- **Where they disagree, the maintainer's own file is the cause.** #297 says that where an
  oracle and our labels disagree, ours are investigated first. The tool rejects 61 sides that
  are the maintainer's set. For 60 of them it also rejects the maintainer's own merged file:
  the maintainer committed a lock file the tool calls inconsistent, and the side matches it.
  The one left is a pnpm file. So the maintainer's-set label is not contradicted by the tool. It
  records an inconsistent state some maintainers chose.
- **The other way, the tool is weaker than the maintainer.** It passes 52 npm and 154 Composer
  sides that are not the maintainer's set. A lock file can satisfy the merged manifests and still
  not be the one committed. Several resolutions are consistent, and the maintainer picked one.
- **As a guide to the side to take, it is right about two times in three.** Where exactly one side
  passes, that side is the maintainer's set in:
  - npm: 57 of 86 files;
  - pnpm: 15 of 18;
  - Composer: 117 of 179.

### The runs that failed

| tool | cause | sides and controls |
| --- | --- | ---: |
| npm | `ERESOLVE`, peer-dependency conflicts. Mostly `PrefectHQ/prefect` (15) and `laurent22/joplin` (9) | 31 |
| npm | `E403` from the registry, 13 of them `nightscout/cgm-remote-monitor`'s | 14 |
| npm, Composer | no lock file on that side | 4 |
| pnpm | `rust-lang/crates.io` pins pnpm 8.6–10.15 in `engines`, not `packageManager`; 10.28 ran, and the engine check refused it | 9 |
| pnpm | `element-hq/element-web`, a lock file pnpm cannot read | 2 |

## Inherited, or made by the merge? (`own_trees.py`, exploratory)

One maintainer merge in seven fails the check, which means little without a base rate. So each
conflicted file's lock file was also checked at three ordinary commits, each **in its own tree**:
the merge's two parents and their merge base. The checks are the same as above.

| tool | ordinary commits: the lock file rejected in its own tree | merged files rejected | of those, both parents passed | of those, a parent failed |
| --- | --- | --- | ---: | ---: |
| npm | 24 of 597 (0.04 [0.03, 0.06]) | 26 of 200 (0.13 [0.09, 0.18]) | 15 | 10 |
| pnpm | 0 of 132 (0.00 [0.00, 0.03]) | 5 of 42 (0.12 [0.05, 0.25]) | 5 | 0 |
| Composer | 25 of 1,076 (0.02 [0.02, 0.03]) | 54 of 359 (0.15 [0.12, 0.19]) | 41 | 13 |
| **all** | **49 of 1,805 (0.03 [0.02, 0.04])** | **85 of 601 (0.14 [0.12, 0.17])** | **61** | **23** |

Intervals are Wilson. A commit is counted once for each file and case it serves, so some recur.
Files where a run failed are left out of each figure. `own_summary.txt` gives them all.

- **Resolving a lock-file conflict makes an inconsistent lock file about five times as often as
  an ordinary commit has one:** 0.14 against 0.03.
- **Most are made by the merge, not inherited.** Of the 85 rejected merged files, both parents'
  own files passed in 61. The reverse is rare: where a parent's file failed (29 files), the
  merge repaired it in 6.
- **It is not a few repositories' habit.**
  - The 61 are spread over 24 of the 45 repositories, at most 8 in any one.
  - By repository, the merged files' rejection rate is above the repository's own base rate in
    26 and below it in 2, with 17 the same (two-sided sign test p = 3e-06).
- **Composer's content-hash shows the same thing, more often.** It is stale on 7% of ordinary
  commits' lock files (77 of 1,076) and 29% of merged ones (104 of 359). A maintainer who
  settles `composer.lock` by hand, or by taking a side, leaves a hash Composer itself would
  have rewritten.

This is the strongest support yet for treating lock-file conflict resolution as a task worth
automating with a check. The check is cheap, offline for Composer, and it catches a defect
that merges introduce far more often than ordinary commits do. As everything here, it is
exploratory: the merges are the studies' conflicted merges, chosen for having a conflict, not a
sample of all merges.

## The check as a precondition (`dispatch.py`, exploratory)

The project's thesis is that a check which is run, rather than a similarity which is guessed,
should decide when a stored resolution fires. Two such checks exist for these files:

- **the divergence gate** (study 5): no package was changed by both sides to different
  versions. It licenses the per-ecosystem merge study 4 predicts.
- **the tool's check:** exactly one side's lock file passes the ecosystem's own check in the
  merge's tree. It licenses taking that side.

Each rule below fires a resolution or refuses. A fire is right when it is the maintainer's
package set. The rules are scored on all 610 files, pooled over 45 repositories (`dispatch.txt`
gives each study and each tool):

| rule | fires (coverage) | wrong | mismatch [95% Wilson] |
| --- | ---: | ---: | --- |
| A: the merge, always | 610 (1.00) | 369 | 0.60 [0.57, 0.64] |
| B: the gate's merge, else refuse | 247 (0.40) | 69 | 0.28 [0.23, 0.34] |
| C: the side the tool alone accepts, else refuse | 283 (0.46) | 94 | 0.33 [0.28, 0.39] |
| **D: the gate's merge; else the side the tool alone accepts; else refuse** | **423 (0.69)** | 134 | **0.32 [0.27, 0.36]** |
| E: as D, the tool asked first | 423 (0.69) | 139 | 0.33 [0.29, 0.37] |
| F: control, no tool: the gate's merge, else the first parent's file | 610 (1.00) | 269 | 0.44 [0.40, 0.48] |

- **Two executed checks together cover far more than either alone, at about the same error.**
  D fires on 0.69 of files against the gate's 0.40, and its mismatch rises from 0.28 to 0.32.
  The same holds in each study:

  | | the gate (B): coverage, mismatch | D: coverage, mismatch |
  | --- | --- | --- |
  | study 3 | 0.32, 0.35 | 0.60, 0.36 |
  | study 4 | 0.49, 0.23 | 0.75, 0.28 |
  | study 5 | 0.44, 0.26 | 0.76, 0.30 |

- **What the tool adds beyond "take your own branch" is real, and small.** Where the tool accepts
  one side, it is the first parent's in 223 of 283 files. The anatomy found that maintainers keep
  their own branch's versions about twice as often as the incoming side's. So the control is the
  first parent's file on the same files. On the 176 files where a package diverges and the tool
  fires:
  - the tool's side is right on 111, the first parent's on 91;
  - paired, the tool's side is right where the first parent's is wrong on 20 files, and never
    the reverse (exact McNemar p < 0.001);
  - by repository, the tool does better in 9, worse in none, and the same in 25.

  With the first parent's file in place of the tool's pick, D's mismatch would be 0.36 instead
  of 0.32.
- **The tool never does worse than the first parent's file, and the reason is structural.** For
  the tool to take the second side, the first side must fail the check. A side that fails is
  almost never the maintainer's set, because the maintainers' own merged files mostly pass
  (above). So the check is a safe tie-breaker: it can only move a fire away from a side that is
  likely wrong.
- **The gain is concentrated.** 12 of the 20 files are one pnpm repository's. pnpm's merge is
  wrong on 43 of 47 files, and the tool's pick is right on 15 of 18. Without pnpm, the tool beats
  the first parent's file on 8 files in 8 repositories. That is study 5 and study 3 only; study 4
  shows none.
- **Nothing here is near "rarely wrong".** The best rule is wrong on about a third of its fires,
  and all of this was found on data already seen. A registration would fix rule D, and the order
  of its checks, before mining fresh repositories.

## What it shows, and what it does not

- **The tool's check is a necessary condition, not an oracle of the answer.** It is mostly
  passed where a side is the maintainer's resolution. It passes many sides that are not, so it
  cannot label which consistent resolution a maintainer chose.
- **Studies 3–5's labels survive it.** Every disagreement with the maintainer's set but one is
  a maintainer's own inconsistent lock file.
- **A labeller using the tool's check would need a rule for inconsistent merges.** One merge in
  seven is committed inconsistent. Treating "consistent" as "correct" would call those
  maintainers wrong.
- **The computed merges are not checked.** `three_way` and `three_way_unified` yield package
  sets, not lock files, so no tool can judge them as they stand.
- **It tests nothing.** It is descriptive, on data seen before. Yarn, Poetry, Cargo and Bundler
  were not checked. Running their tools on these repositories was not among what the owner
  approved, and a `Gemfile` is Ruby code.
