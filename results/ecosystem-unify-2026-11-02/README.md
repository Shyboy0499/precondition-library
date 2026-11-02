# Study 4: the resolver predicts which package-level merge maintainers kept, 2026-11-02

**Confirmatory**, run as registered in `docs/preregistration/ecosystem-unify.md` (ADR-0058) at
commit `7176d5c`, the registration's own. Its commit was pushed before the run started.

```bash
python -m precondition_library.bench.ecosystem_unify --out results/ecosystem-unify-2026-11-02
```

**An interruption, not a deviation.** The first run was killed by a container restart after 18
of the 20 repositories. A run writes its files only at the end, so nothing of it was kept or
looked at beyond the per-repository case counts in its log (`run.interrupted.log`). It was rerun
from the start at the same commit (`run.log`). The 18 repositories it had finished gave the same
case counts both times.

## Result: all four hypotheses are supported

**266 conflicted cases from 20 repositories.** The target was at least 12. Excluded or passed
over:

| reason | cases |
| --- | ---: |
| criss-cross merge | 53 |
| submodule or binary conflict | 5 |
| the maintainer's merged lock file could not be read | 4 |

| hypothesis | discordant files won / lost by the prediction | repositories voting for / against / tied | sign-test p | outcome |
| --- | ---: | ---: | ---: | --- |
| **H1**: both families | **91 / 0** | 17 / 0 / 0 | 1.5 × 10⁻⁵ | **supported** |
| **H2**: one-version family, unified predicted | 24 / 0 | 10 / 0 / 0 | 0.002 | supported |
| **H3**: npm's family, plain predicted | **67 / 0** | 11 / 0 / 0 | 0.001 | **supported** |

**H4 replicates study 3.** Mean coverage over repositories is 0.760 [0.674, 0.845], against
study 3's 0.686, so H4 is supported.

## Descriptive figures

| action | cases reproduced |
| --- | ---: |
| the resolver's merge (`three_way` for npm's family, `three_way_unified` otherwise) | **0.553** |
| `three_way` | 0.466 |
| `take_local` | 0.387 |
| `three_way_unified` | 0.316 |
| `take_upstream` | 0.132 |

| lock file | conflicted files | some action reproduces | only `three_way` | only `three_way_unified` |
| --- | ---: | ---: | ---: | ---: |
| `composer.lock` | 97 | 85 | 0 | 15 |
| `yarn.lock` | 75 | 55 | 44 | 0 |
| `package-lock.json` | 56 | 41 | 23 | 0 |
| `Gemfile.lock` | 42 | 30 | 0 | 9 |
| `pnpm-lock.yaml` | 15 | 8 | 0 | 0 |
| `Cargo.lock` | 5 | 4 | 0 | 0 |

## What it shows, and how strongly

- **H3 is the test that could have failed, and it held without exception.** In npm's family,
  where compatible duplicates can coexist, a maintainer could have deduplicated or kept both
  versions, so either merge can win a discordant file. On fresh repositories the plain merge won
  all 67, in all 11 repositories that had one. Maintainers keep the duplicates.
- **H2 tested much less than its sign test suggests.** This was found after the data, and the
  registration did not foresee it. In a one-version ecosystem the maintainer's file holds one
  version per package. A plain merge holding two versions of a package therefore cannot match
  it, and that is the case in 74 of the 144 one-version files here. A plain merge holding no
  duplicates is unchanged by unifying, so the two merges agree. So a discordant one-version file
  can go against the prediction only in the rare lock file that legitimately holds two versions
  of a package. That happened once in study 3, in a `poetry.lock` with two versions under
  different markers. H2's 24/0 says how often unification gives the exact answer, not that
  maintainers prefer it.
- **H1 pools both families**, so part of its support is H2's. It is supported as registered, but
  its weight rests on H3.
- **The rule is worth having.** One merge chosen per ecosystem reproduces 55% of cases, against
  47% for the better of the two fixed merges.
- **Study 3's headline replicates.** On 20 new repositories, about three conflicts in four have a
  computed action that gives exactly the maintainer's package set.

## A determinism defect found while verifying, and its reach

`lock_actions.unify` keeps the highest version within each compatible range, iterating over a
set. Two versions whose release numbers are equal can both be the highest: for example a
pre-release and its release, since `_release` drops the pre-release suffix. The one kept is then
whichever the set yields first, which can differ between Python processes.

`verification/ties.py` checks every labelled file:

- **Study 4:** 34 files contain such a tie.
- **None of those 34 verdicts depends on the tie-break.** Every choice gives the same "reproduces"
  answer, so no figure above can change. Only some Jaccard values can move, in the third
  decimal.
- **Study 3 is checked the same way**, in a separate commit.

The defect is fixed for future runs in `bench.lock_actions` with a deterministic tie-break, in a
separate commit. These results are from the registered code.

## Verification

Each script is in `verification/` and was written after the run.

- **`recompute.py`** uses the standard library only and imports nothing from the project. From
  `labels.jsonl`, it re-derives every discordant file, vote, sign test, H4's interval and
  decision. All 23 comparisons agree, with 0 mismatches.

  ```bash
  python -I results/ecosystem-unify-2026-11-02/verification/recompute.py results/ecosystem-unify-2026-11-02
  ```

- **`rederive.py`** re-reads all 290 conflicted lock files from git, at the SHAs in
  `manifest.json`, with parsers and a unification written in the script itself. Its verdicts for
  all four actions agree with `labels.jsonl` on every file. A few unified Jaccard values differ,
  in the third decimal at most, because of the tie-break above. Neither its verdicts nor the
  project's depend on that choice. It also counts the 74 one-version files whose plain merge
  holds duplicates.
- **`ties.py`** is the check above.

`rederive.py` and `ties.py` need the run's repository caches, so they are kept as records rather
than re-run by CI.
