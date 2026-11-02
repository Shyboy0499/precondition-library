# Study 3: which computed action reproduces a maintainer's lock file, 2026-11-02 (#306)

**Confirmatory**, run as registered in `docs/preregistration/lock-oracle.md` (pin `3e9afab2…`,
ADR-0056) at commit `51ad738`, the registration's own. There were no deviations from the text.

```bash
python -m precondition_library.bench.lock_oracle --out results/lock-oracle-2026-11-02
```

The run took well under an hour and needed no API key. It fetched the 27 registered repositories
at their default branches' tips, pinned in `manifest.json`. `run.log` is its output.

## Result: both hypotheses are supported

**360 conflicted cases from 27 repositories.** The registered targets were at least 150 cases and
at least 15 repositories. Twenty-one cases were passed over or excluded, by §3.2 and §3.4:

| reason | cases |
| --- | ---: |
| criss-cross merge | 9 |
| the maintainer's merged lock file could not be read | 10 |
| submodule or binary conflict | 2 |

| figure (mean over repositories, 95% t-interval) | value | rule | outcome |
| --- | --- | --- | --- |
| **H1** coverage: some computed action reproduces the maintainer's package set exactly | **0.686** [0.601, 0.770] | lower end above 0.10 | **supported** |
| **H2** `J(three_way_unified) − J(take_local)` | **+0.069** [0.023, 0.115] | both lower ends above 0 | **supported** |
| **H2** `J(three_way_unified) − J(take_upstream)` | **+0.113** [0.069, 0.156] | | |

- **H1.** About two in three real lock-file conflicts have an answer computed from the base and
  the two sides alone, with no tool, no registry and no judgement. It is the exact package set
  the maintainer committed. The pooled share over cases is 0.683, close to the per-repository
  mean.
- **H2.** The package-level three-way merge is closer to what maintainers committed than either
  side taken whole.

## Descriptive figures (§7, no hypothesis)

| action | cases reproduced | median per-case Jaccard |
| --- | ---: | ---: |
| `take_local` | 0.281 | 0.974 |
| `take_upstream` | 0.131 | 0.935 |
| `three_way` | **0.389** | **0.996** |
| `three_way_unified` | 0.319 | 0.986 |
| study 1's line unions, line for line | 0.072 | |

| lock file | conflicted files | reproduced by some action |
| --- | ---: | ---: |
| `composer.lock` | 136 | 102 |
| `package-lock.json` | 116 | 79 |
| `Gemfile.lock` | 85 | 65 |
| `yarn.lock` | 34 | 20 |
| `poetry.lock` | 20 | 11 |
| `Cargo.lock` | 18 | 9 |
| `pnpm-lock.yaml` | 3 | 2 |

Coverage by repository runs from 0.27 (`rust-lang/crates.io`) to 1.0 (three repositories).

## What it shows

- **The lock-file task can have an external oracle.** On fresh repositories, 69% of real
  conflicts get a label nobody here wrote, the maintainer's own. The pilot's 33%, on six
  repositories already seen, underestimated it.
- **The package-level formulation is the right one.** Study 1's line unions reproduce 7% of the
  same cases. Package sets reproduce 69%.
- **Merging is the right starting point, not either side.** H2 holds against both sides, and
  `three_way` alone reproduces more cases than any other single action.

## Exploratory: where unification helps, and where it hurts

This was not registered, and was found after looking at the data. Per conflicted file, the
figures are the files `three_way` reproduces and `three_way_unified` does not, and the reverse:

| lock file | only `three_way` | only `three_way_unified` |
| --- | ---: | ---: |
| `composer.lock` | 0 | 25 |
| `Gemfile.lock` | 0 | 4 |
| `poetry.lock` | 1 | 2 |
| `package-lock.json` | 27 | 4 |
| `yarn.lock` | 13 | 0 |
| `pnpm-lock.yaml` | 2 | 0 |
| `Cargo.lock` | 0 | 0 |

- **Unifying helps where the resolver installs one version of each package** (composer,
  bundler, poetry). There, both sides' bumps of one package cannot both stay.
- **It hurts in npm's family.** There, compatible duplicate versions coexist in nested
  `node_modules`, and maintainers keep them.

A lock-file action set built from this would unify per ecosystem: composer, Gemfile and poetry
yes; npm, yarn and pnpm no. That rule is a hypothesis for a future registration. Nothing here
tests it.

## What it does not show

- **That any dispatcher picks the right action.** This labels the cases. No library has been
  measured on them.
- **What the uncovered 31% are.** They are near-misses by Jaccard: the median for `three_way` is
  0.996. Most likely the maintainer also ran a tool against that day's registry, as stage A
  suggested. This study does not test that.
- **Anything about clean merges.** Only conflicted merges are cases here.

## Verification

Both scripts are in `verification/`, written after the run and kept as the record of the checks.

- **`recompute.py`** uses the standard library only and imports nothing from the project. From
  `labels.jsonl`, it re-derives each case's verdicts, Jaccards and coverage from its per-file
  results. It then recomputes every figure, interval and decision in `report.json`.
  - All 28 comparisons agree, with 0 mismatches.
  - It also checks that no repository has more than 15 cases.

  ```bash
  python -I results/lock-oracle-2026-11-02/verification/recompute.py results/lock-oracle-2026-11-02
  ```

- **`rederive.py`** re-reads all 412 conflicted lock files from git, at the SHAs in
  `manifest.json`, with parsers written in the script, independently of `bench.lock_actions`.
  - Its verdicts and Jaccards for `take_local`, `take_upstream` and `three_way` agree with
    `labels.jsonl` on all 1,236.
  - No maintainer file is read as empty. The smallest holds 2 packages and the median 228. So
    no "reproduction" is empty matching empty.
  - Only 7 of the 360 cases have identical package sets on both sides. Those are conflicts
    outside the packages, such as composer's `content-hash`, where any action reproduces.
    Without them, coverage is still about two in three.
  - It needs the run's repository caches, so it is kept as a record rather than re-run by CI.
