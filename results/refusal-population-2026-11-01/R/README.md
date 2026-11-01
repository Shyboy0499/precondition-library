# Study 2's refusal set R, frozen 2026-11-01 (refusal-population §3.3, §4 step 3)

R is the set of real lock-file conflicts that configuration R's programs must refuse. It was mined
from list A, in the registered order, by the registered code on main at `b320f32`. That code
requires the registration, as amended by Amendment 1, before it mines anything:

```bash
python -m precondition_library.bench.refusal_study mine-refusals \
  --out results/refusal-population-2026-11-01/R
```

**Committing this directory freezes R.** A configuration R build reads it through
`bench.live --refusal-set`. Every rebuild of a state is compared with `states.jsonl.gz`, and
`build.json` records the set's SHA-256:

```
044a77da17c06b39335dc4e7b8c7a442994fd0f3eb6ace4c6ee0435c19fc46b5
```

That is `refusal_set.digest`: `refusal-set.json` and `states.jsonl.gz`, in that order. No build has
run, and the evaluation set has not been mined.

## What R holds

**35 inexpressible conflicts, from all four repositories.** §3.3 takes at most 10 per repository,
the most recent first, until there are 40 *or list A is exhausted*. matomo has only 5, so list A ran
out at 35.

| repository | tip | two-parent merges | in R | excluded |
| --- | --- | ---: | ---: | ---: |
| [matomo-org/matomo](https://github.com/matomo-org/matomo) | `781186d8170c` (6.x-dev) | 2,635 | 5 | 5 |
| [saleor/saleor](https://github.com/saleor/saleor) | `cc4aea76e397` (main) | 3,685 | 10 | 0 |
| [openfoodfoundation/openfoodnetwork](https://github.com/openfoodfoundation/openfoodnetwork) | `dc210ad0c2cb` (master) | 7,495 | 10 | 0 |
| [RocketChat/Rocket.Chat](https://github.com/RocketChat/Rocket.Chat) | `9971f492da49` (develop) | 5,791 | 10 | 3 |

- **Every case is inexpressible:** all 35 acceptable sets are empty, by study 1's §4 rule under its
  Amendment 1.
- **The lock files:** `Gemfile.lock` 10, `yarn.lock` 10, `poetry.lock` 9, `composer.lock` 5,
  `package-lock.json` 1.
- **Other conflicted paths:** 7 cases conflict only in the lock file. The rest also conflict in
  other paths, which makes them inexpressible by §4's rule whatever the lock file holds.
- **How the maintainers resolved them:** they regenerated the lock file on 20, did something else
  on 13, took upstream's on 1 (matomo) and the local one on 1 (Rocket.Chat). By repository,
  saleor regenerates (9 of 10) and openfoodnetwork mostly does something else (9 of 10).
- **Exclusions, as study 1 defines them:** 5 conflicts that also conflict in a submodule or a
  binary file (all matomo), and 3 criss-cross merges (all Rocket.Chat).
- **Licences**, as each tip's licence file names itself: GPL, BSD, AGPL, MIT. Only SHAs, paths
  and derived labels are committed, never the repositories' content.

## How long the refusal check takes (ADR-0054 item 3)

ADR-0054 rebuilds R's states for every program the gate checks, rather than keeping forty
checkouts, and promised to measure the cost once R existed. `time_refusal_check.py` puts each
admitted program of one committed library (replicate 2, 14 programs) through
`RefusalStates.accepted_by`, the call a configuration R build makes per candidate:

| | seconds per program |
| --- | ---: |
| first program, which also fetches the four histories | 279.6 |
| the other 13, histories cached | mean **153.9**, 113.1–187.3 |

That is about 4.4 s per state. A build sends roughly 14–20 candidates through the refusal side, so
a configuration R build gains about 35–60 minutes, against about two hours of model calls. **The
mechanism stands as ADR-0054 describes it**, and nothing needs to change before the builds.

**Incidentally, what R refuses in that old library.** This is a description of programs built
for study 1. It decides nothing, and study 2's builds are new ones (`timing.json`).

- 12 of the 14 programs refuse every state of R.
- The lock-file `take_upstream` program fires on 1 saleor conflict.
- The `submodule_moved` program that initialises a submodule fires on all 5 matomo conflicts.
  matomo has git submodules, which a fresh checkout leaves uninitialised, so the program's
  preconditions see a submodule to initialise on a lock-file conflict.

Configuration R's rule would have refused both programs. This is the kind of wrong fire on an
unanticipated state that the rule is meant to catch.

## Files

- `refusal-set.json`: the repositories (URL, tip, default branch, licence, counts), the 35 cases
  (merge, parents, base, conflicted paths), their labels and the 8 exclusions.
- `states.jsonl.gz`: each case's state as `StateFingerprint.observe` read it, as a frozen copy.
- `repos/`: the per-repository parts mining wrote as it went, which a resumed mining reads back.
- `mine.log`: the mining run, 04:58–05:05 UTC.
- `time_refusal_check.py`, `timing.json`, `timing.log`: the timing measurement.
