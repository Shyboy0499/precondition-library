# Real lock-file merge conflicts, labelled by what maintainers committed

**1,559 lock-file merge conflicts from 109 open-source repositories**, across nine formats. Each
conflict is identified by its commits and labelled from what the project's maintainer actually
committed.

| ecosystem | lock file | conflicts | repositories |
| --- | --- | --- | --- |
| Composer | `composer.lock` | 522 | 45 |
| npm | `package-lock.json` | 375 | 45 |
| Yarn | `yarn.lock` | 231 | 24 |
| pnpm | `pnpm-lock.yaml` | 143 | 12 |
| Bundler | `Gemfile.lock` | 140 | 12 |
| Cargo | `Cargo.lock` | 105 | 12 |
| Poetry | `poetry.lock` | 26 | 3 |
| Pipenv | `Pipfile.lock` | 15 | 2 |
| uv | `uv.lock` | 2 | 1 |

It is built for evaluating anything that resolves lock-file conflicts: merge drivers, package
managers' auto-resolution, AI coding agents, or a new rule. Answers can be graded against the
maintainer's resolution, a validity check, or both.

## What a row is

One lock file conflicted in one real merge. A merge is a two-parent commit on the repository's
default branch whose parents, re-merged with `git merge-tree`, conflict in that file. For each
row you get:

| field | meaning |
| --- | --- |
| `id` | `owner/repo@<merge[:12]>:<path>` |
| `repo`, `repo_url`, `licence` | the repository and its licence, as detected |
| `path`, `lock_file`, `ecosystem` | the conflicted lock file |
| `merge` | the maintainer's merge commit |
| `ours`, `theirs` | its first and second parent |
| `base` | their merge base |
| `other_conflicted_files` | what else conflicted in the same merge (`jsonl` only) |
| `studies` | which of the source studies mined it |
| `maintainer_file` | `present`, `deleted`, `conflict markers` (committed with markers), or `unreadable` |

For the 1,550 rows whose maintainer file is present and readable:

| field | meaning |
| --- | --- |
| `reproduces.take_ours`, `.take_theirs` | that side's lock file has the maintainer's resolved packages |
| `reproduces.three_way` | so does the package-level three-way merge: what both kept, plus each side's additions, less each side's removals |
| `reproduces.three_way_unified` | the same, keeping the higher version where both sides moved a package |
| `packages_changed.ours`, `.theirs` | packages each side changed since the base |
| `packages_diverged` | packages both sides changed, to different versions |
| `maintainer_versions_new` | resolved versions in the maintainer's file that neither side had (a sign they re-ran the package manager) |

"Reproduces" compares **resolved `(package, version)` sets**, ignoring formatting, ordering,
hashes and format version. That is the comparison the source studies used.

For `package-lock.json` and `composer.lock` only:

- **`maintainer_valid`:** the maintainer's file passes the package manager's consistency rules
  for the merged manifest, checked offline:
  - npm: every declared dependency is locked, in range;
  - Composer: the `content-hash` is fresh and every requirement is met.
- **`lockmerge_0_1_0`:** what [lockmerge](../../lockmerge/README.md) 0.1.0 did, whether its
  result is valid, and whether it has the maintainer's packages.

## What it shows at a glance

On the 1,550 labelled rows:

| ecosystem | rows | ours | theirs | three-way | unified | any of the four | packages diverged = 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| composer | 521 | 239 | 71 | 176 | 257 | 406 | 240 |
| npm | 374 | 157 | 69 | 124 | 7 | 259 | 158 |
| yarn | 230 | 51 | 33 | 84 | 2 | 125 | 93 |
| pnpm | 141 | 37 | 20 | 35 | 9 | 83 | 47 |
| bundler | 140 | 11 | 12 | 81 | 97 | 104 | 109 |
| cargo | 103 | 12 | 15 | 42 | 45 | 57 | 53 |
| poetry | 26 | 3 | 2 | 8 | 9 | 12 | 15 |
| pipenv | 13 | 1 | 2 | 8 | 7 | 10 | 11 |
| uv | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| **all** | **1,550** | | | | | **1,058 (68%)** | |

In about two conflicts in three, one of four simple, deterministic actions gives exactly the
maintainer's packages, the same rate study 3 registered (0.686). In the remaining third the
maintainer did something else: re-resolved, hand-edited, or changed versions neither side had.

## Getting the file contents

The dataset holds **no file content** from any repository: only commits, paths and derived
labels. Each version is one request away:

```text
https://raw.githubusercontent.com/<repo>/<commit>/<path>
```

`build.py` fetches all four versions of every row into a local cache and recomputes every label.

```bash
PYTHONPATH=src:lockmerge/src python datasets/lockfile-conflicts/build.py --cache DIR
```

The maintainer's merged manifest (`package.json`, `composer.json`, …) is at the same commit as
`merge`.

## How it was collected, and its limits

- **Source.** The rows are the positive cases of this repository's studies:
  - study 1 (`results/real-merges-2026-10-26/`);
  - studies 3–6 (`results/lock-oracle-2026-11-02/`, `ecosystem-unify-2026-11-02/`,
    `divergence-gate-2026-11-08/`, `tool-precondition-2026-11-09/`).

  Each study's registration (`docs/preregistration/`) fixed its repositories, mining rules and
  exclusions before its data was seen.
- **Selection.**
  - Repositories were chosen because they had lock-file conflicts.
  - Each study capped how many cases one repository contributes, keeping the most recent.
  - The set is not a random sample of all merges.
- **Exclusions.** Mining excluded criss-cross merges and conflicts in submodules or binary files.
  It ran without the repositories' `.gitattributes`; the audit in
  `results/mining-attributes-2026-11-08/` found this affects three cases.
- **One answer.** The maintainer's commit is one acceptable resolution, not the only one. A
  different resolution that installs and passes the project's tests may be just as good. Use
  `maintainer_valid` (and your own checks) as well as `reproduces`.
- **Duplicates.** A merge mined by several studies appears once, with every study listed.

## Licence and citation

The labels and this documentation are released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The repositories' own content is not
redistributed, and each row records its repository's licence.

When citing it, cite the dataset,
[doi:10.5281/zenodo.24544756](https://doi.org/10.5281/zenodo.24544756), and the report,
[doi:10.5281/zenodo.24544472](https://doi.org/10.5281/zenodo.24544472). Version 1 on Zenodo is
this folder at commit `0d4d36f`.

## Files

- `conflicts.jsonl`: one JSON object per row, with every field above.
- `conflicts.csv`: the same rows, flattened to the main fields.
- `build.py`: rebuilds both from the committed study manifests.
