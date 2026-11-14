# Can a project's own tests judge a lock-file resolution? A pilot, 2026-11-14

**Pilot, not a study.** #297's third oracle is the project's own test suite. Running it
executes the studied projects' code, so the owner approved only a sandboxed pilot (2026-11-13):
a few repositories whose suites need no database or service, one merge each, install scripts
off and tests offline. It asks what is feasible, and it decides nothing.

## Method

`pilot.py` takes one case per repository from studies 3 and 6: a merge whose conflict includes
a `package-lock.json` or `composer.lock`. Exactly one parent's file in each case is the
maintainer's package set, so the two parents' files can be told apart. For each case it builds
three trees:
- **maintainer:** the merge's tree, as committed;
- **first** and **second:** the same tree, with the conflicted lock file replaced by that
  parent's.

The trees are written from the commit's blobs, not with `git archive`, which leaves out files
marked `export-ignore`, test directories among them. In each tree it:
1. **installs with every lifecycle script off**, using `npm ci --ignore-scripts` (one retry);
2. **runs the project's unit tests with no network.** They run under `unshare -n`, with only the
   loopback interface up and a 20-minute limit.

The maintainer's tree is tested twice, to see whether the suite repeats. Only the suite's own
summary lines are kept. A failing run's last lines went to a local log, because they can name
packages.

| repository | case | command |
| --- | --- | --- |
| `louislam/uptime-kuma` | study 6, 105 | `npm run test-backend` (the Playwright end-to-end suite is left out) |
| `nextcloud/nextcloud-vue` | study 6, 326 | `vitest run` |
| `node-red/node-red` | study 3, 288 | `grunt simplemocha:core` |
| `getgrav/grav` | study 3, 77 | `codecept run unit`: not run, see below |
| `filamentphp/filament` | study 6, 16 | `pest`, SQLite configuration: not run, see below |

## Result

| repository | maintainer's tree, run twice | the parent whose file is the maintainer's set | the other parent |
| --- | --- | --- | --- |
| uptime-kuma | 74 tests: 20 pass, 37 fail, both times (142 s) | the same counts | `npm ci` refuses the lock file (`EUSAGE`, out of sync) |
| node-red | 1,256 passing, 31 pending, 8 failing, both times (11 s) | the same counts | `npm ci` refuses the lock file (`EUSAGE`) |
| nextcloud-vue | `npm ci` fails: a git dependency did not install (exit 128) | — | — |

What it shows:
- **Where a suite runs, it runs offline and repeats exactly.** Both baselines gave the same
  counts twice.
- **The maintainer's own merge fails tests.** So the oracle cannot be "all tests pass". It has
  to compare a resolution's results with the maintainer's, ideally test by test. The pilot kept
  only counts, which are weaker: the same counts could hide different failing tests.
- **In these cases the tests added nothing beyond the consistency check.** The wrong parent's
  lock file was refused by `npm ci` itself before any test ran. That follows from how the cases
  were chosen: one side right, one wrong.
- **Where tests could add something** is a file where both parents' lock files pass the check:
  the tie the check cannot break. A next step would choose those cases, and record failing tests
  by name.

## What did not run

- **nextcloud-vue.** One dependency is a git repository, and `npm ci` could not install it,
  twice.
- **grav and filament (Composer).** Composer downloads packages from `codeload.github.com`,
  which this session's network policy refuses. It then fell back to cloning every dependency
  with git, which timed out and filled 14 GB of disk before it was stopped. The owner has an
  environment that allows the host (`precondition-library`). A session on it can run
  `pilot.py ... composer`.
- **A first attempt is not counted.** Without the loopback interface, node-red's suite failed at
  once and uptime-kuma's ran past the time limit. That run's rows were discarded and every row
  here was rerun with loopback.

## Files

- `pilot.py`: the pilot. Run it as
  `python -I results/project-tests-pilot-2026-11-14/pilot.py <out.jsonl> <scratch> [npm|composer]`.
- `runs.jsonl`: one row per tree and attempt. Each row has the label, the install outcome, and
  the test exit code, duration and summary lines.
