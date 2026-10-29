# ADR-0053 — Study 2 is registered: refusal over a population of builds, against a state reader given the same evidence

- **Status:** accepted
- **Date:** 2026-10-29
- **Supersedes:** nothing. It follows ADR-0048 (studies on outside data are registered first), and
  takes up ADR-0050's step 3 (#307) and ADR-0052's decision 5.
- **Deciders:** the repository owner chose the size, "10 per config, 2 configs", and asked for the
  registration to be drafted before any key is set. The rest of the design is the author's,
  recorded here to be challenged.

## Context

Study 1 falsified "arm 3 rarely mis-fires" on real lock-file merges (ADR-0052). Its H2 margin
over reading the state turned out to be the control's narrower scope. Exploratory analysis
afterwards found that a control given arm 3's scope is right on clean merges as often as arm 3,
but fires on every conflict nothing can express, where two of three libraries mostly declined.
That analysis was done after the data was seen, on three builds that fired on 22%, 6% and 82% of
those conflicts, so it supports no claim.

Two questions follow:

- whether declining is a property of executing checks, or only of what a build happened to
  admit;
- whether admission can select for declining (#307).

## Decision

1. **Register study 2 before any of its data exists:**
   `docs/preregistration/refusal-population.md`, pinned as `refusal-population`.
2. **A population, not a replicate.** Each configuration has 10 builds. Build `b` permutes the
   admit-set plan with seed `b`, and the same permutations serve both configurations. Every figure
   is reported as a distribution over builds.
3. **Two configurations that differ in one rule:**
   - configuration 0 is the current two-sided gate;
   - configuration R also admits a program only if its preconditions refuse every state in R. R is
     up to 40 real inexpressible conflicts from four admission repositories, never part of the
     evaluation.
4. **Like-for-like controls:**
   - Control-0 is the library-scoped state reader, fitted as study 1 fitted the registered
     control;
   - Control-R is the same reader also trained on R, labelled "fire nothing";
   - the primary hypothesis compares configuration R with Control-R, so both get the same refusal
     evidence. Only that comparison can say executing checks declines better than reading the
     state.
5. **New repositories only, in fixed order:** R is mined first, the builds are frozen, and only
   then is the evaluation set mined.
6. **The power is stated, and so is its limit.** With build-to-build spread near 0.4, ten builds
   can detect mean differences of about 0.3 (H1, H2) or 0.4 (H3). Smaller ones may be real and
   undetected.

## Consequences

- The study's code (the build ordering, refusal-tested admission, Control-R and the runner) is a
  separate change, reviewed before any build, and bound by `preregistration.require`.
- It runs only once `DEEPSEEK_API_KEY` is set in the environment settings. Twenty builds cost
  about 20 times one build's tokens.
- A null on H1 would mean declining is not, on this evidence, a property of executing checks. The
  project's remaining claim would then be the engineering one: replay without a model call.

## Alternatives considered

- **Re-analyse stage B with the library-scoped control as the result.** Rejected: that data has
  been seen. The analysis is kept, labelled exploratory.
- **Compare configuration R with Control-0.** Rejected as the primary hypothesis: configuration R
  would have seen the refusal set and the control would not, so a difference could be the
  evidence, not the execution.
- **Vary temperature to make builds differ.** Rejected: temperature 0 is pinned and recorded
  (#6). The permutation varies the build's path without changing the model's settings, and the
  provider's nondeterminism at temperature 0 remains.
