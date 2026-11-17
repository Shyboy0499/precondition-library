# Study 2: refusal over a population of builds, 2026-11-15 to 2026-11-17

This is the registered result of `docs/preregistration/refusal-population.md` (#307). The question
(§1):

> On real conflicts that no resolution can express, does executable-precondition dispatch
> decline more often than a state-reading control that was given the same evidence, and does
> admitting only programs that decline known such conflicts make it decline more?

**The design.**

- **Configuration 0:** 10 libraries built with the current admission rule.
- **Configuration R:** 10 built with refusal-tested admission. A program must also decline every
  state of the frozen refusal set R (`results/refusal-population-2026-11-01/R`).
- **The controls:** each configuration is compared with a state-reading control given the same
  evidence: Control-0, fitted as study 1 fitted it, and Control-R, also taught R's states as
  "fire nothing".
- **The evaluation set:** real merges from repositories no build saw (list E), labelled by what
  the maintainers committed.

## Result

The evaluation set is 209 cases from 8 repositories: 109 inexpressible conflicts, 97 clean
merges and 3 other conflicts. Both configurations have 10 valid builds, so the study is powered
(§8).

| | statistic | 95% interval | §9 |
| --- | --- | --- | --- |
| **H1 (primary)** `f(Control-R) − f(R's builds)` | +0.060 | [−0.009, +0.153] | **not supported** |
| H2 `f(Control-0) − f(0's builds)` | +0.461 | [+0.191, +0.741] | supported |
| H3 `f(0) − f(R)` | +0.516 | [+0.255, +0.774] | supported |
| H4 `right(R) − right(0)` on clean merges (margin −0.10) | −0.296 | [−0.687, +0.098] | not shown |

`f` is a dispatcher's fire rate on the inexpressible conflicts, and lower is better.

| | fire rate on inexpressible conflicts | right on clean merges |
| --- | --- | --- |
| Control-0 | 1.000 | 91 of 97 |
| Control-R | 0.083 | 94 of 97 |
| configuration 0's builds (mean, SD, range) | 0.539, 0.443, 0.009–1.000 | mean 0.681 |
| configuration R's builds (mean, SD, range) | 0.023, 0.025, 0.000–0.064 | mean 0.385 |

Each build's own figures and its repository-clustered margin over its control are in
`summary.txt` and `verification/recompute.txt`.

## What it shows

- **The primary hypothesis is not supported.** Executing checks does not decline better than a
  state reader given the same evidence. Control-R declines 92% of the inexpressible conflicts.
  R's builds decline 98%, and the difference's interval includes 0. On clean merges Control-R is
  right on 94 of 97; the average R build is right on 38%. This is §9 rule 3's primary result.
- **Refusal is a property of the build, not of the method, under the current admission.**
  - Configuration 0's ten builds fire on anywhere from 1% to 100% of the inexpressible conflicts.
    The standard deviation is 0.44, the quantity #307 asked about.
  - Study 1's three builds (22%, 6%, 82%) were not unlucky: this spread is what the method
    produces.
  - H2 is supported because Control-0 fires on everything, as in study 1, not because the builds
    agree.
- **Refusal-tested admission makes builds decline (H3), but its cost on clean merges is not
  resolved (H4).**
  - Under R the fire rate falls to 0–6%.
  - Six of the ten R builds are right on no clean merge, and two (R-5, R-7) fire on no case at
    all. Much of R's declining is libraries that do not fire on these repositories.
  - H4's interval runs from −0.69 to +0.10. A cost larger than the 0.10 margin is neither shown
    nor excluded at this size.
- **The builds that do both are few.** A build that declines inexpressible conflicts *and* is
  right on clean merges can be counted: 0-3 and 0-9 in configuration 0; R-2, R-8 and R-9 under
  R (R-4 fires on 6%). Control-R does both without compiling anything.

## What it does not show

- **That executing preconditions is worse.** H1's interval, [−0.009, +0.153], includes 0. The
  data fit R's builds declining up to 0.15 more often than Control-R, and fit them declining
  slightly less often.
- **Anything beyond lock-file merges in these 8 repositories.** Three repositories of list E
  yielded no case (getredash/redash, forem/forem, zulip/zulip).
- **Why the builds differ.** Within a configuration, the design varies only the admit-set order
  (§5). The compiling model is also not perfectly repeatable at temperature 0. Which programs a
  build admits is not analysed here.

## Deviations

Every one is a change in how the run was carried out, not in what it measures.

1. **The code commit changed between building and evaluating.**
   - **The registration's code.** The registration fixed commit `e7b48ea`. The 20 builds ran on
     it (`builds/README.md`), and the evaluation started on it at 17:33 UTC on 2026-11-15.
   - **Why it was stopped.** At about 28 minutes per case, that run would have taken days, so it
     was stopped at 20:16 UTC with the owner's agreement, before any repository was finished.
   - **The commit that produced every result here.** The evaluation was completed on `0b475a2`.
     Its source differs from `e7b48ea` in five commits:
     - **`4488992` (#374):** faster probing and `--jobs`. On one real case, all 1,943 predicate
       verdicts of the 20 libraries were identical with and without it (spec revision 160).
     - **`0b475a2` (#375):** resuming inside a repository from a journal and a pin. A test shows
       a resumed run writes byte-identical files (spec revision 161).
     - **`96b21b0` (#373):** a compiled `expect_pattern` that Python cannot read as a regular
       expression no longer holds, where it used to crash. It can only change a case on which
       `e7b48ea` would have stopped the run.
     - **`79e4fa7` and `de5e414`:** the judge's token budget and arm 2's floor. The evaluation
       does not call either.
2. **The run was interrupted nine times and resumed each time.**
   - **Causes.** One was stopped deliberately for the speed-up. The others were restarts of the
     session's worker or container, on 2026-11-15 and 16 and twice on the 17th.
   - **What was lost.** From `0b475a2` on, each restart lost only the cases in progress. The
     three runs before it (one on `e7b48ea`, two on `4488992`) had no journal, so each lost its
     partial work on openproject. No figure comes from them.
   - **The record.** `evaluate.log` is the last run's log: start 01:33 UTC, end 10:46 UTC on
     2026-11-17.
3. **Repositories were pinned on the day each was first mined, as §3.1 requires.** openproject
   was first mined on 2026-11-15 and pinned then; every resumed run read that pin rather than
   pinning again. The other ten repositories were first mined, and pinned, on 2026-11-17. Each
   tip is in `manifest.json`.
4. **`repos/` is not committed.** It holds the per-repository files the run writes as it goes,
   so an interrupted run can resume. Every field §10 asks for is in the files below. They are
   26 MB that repeat them.

## Files

- **`summary.txt` and `report.json`:** §7's estimates, each build's figures, the spread and §9's
  decisions.
- **`manifest.json`:** each repository's URL, tip, licence and counts; every case; and each of the
  41 exclusions with its reason (39 criss-cross, 2 a submodule or binary conflict).
- **`labels.jsonl`:** each case's acceptable resolutions.
- **`decisions.jsonl`:** what every build and both controls fired on every case.
- **`states.jsonl.gz`:** each case's observed state.
- **`builds.json`:** the 20 libraries and their digests. Each build's record, its admitted
  programs and its token use are in `builds/`.
- **`evaluate.log`:** the final run's output.
- **`verification/recompute.py` and `recompute.txt`:** an independent recomputation of every
  figure from the files above, using only the standard library and not the project, as §10
  requires. It ends with "every figure matches report.json".

```bash
python results/refusal-population-2026-11-15/verification/recompute.py
```
