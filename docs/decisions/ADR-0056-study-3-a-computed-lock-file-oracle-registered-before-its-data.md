# ADR-0056 — Study 3: a computed lock-file oracle, registered before its data

- **Status:** proposed
- **Date:** 2026-11-02
- **Supersedes:** nothing. It completes the last "done when" of #306 that ADR-0050 set: a
  registration before any fresh case is labelled package by package.
- **Deciders:** the repository owner chose #306 as the next key-free work; the design below is
  the author's, for review.

## Context

The exploratory pilot (`results/lock-actions-2026-10-27/`) read stage A's 30 lock-file conflicts
as sets of `(package, version)` pairs. Some action reproduced the maintainer's set on 10. The
actions computed from the three sides alone did all of that work, while running an ecosystem's
tool today failed on 51 of 144 runs and reproduced nothing the computed ones did not. The pilot
is exploratory, though: it chose its actions after seeing the data, from six repositories.

## Decision

1. **Study 3 (`docs/preregistration/lock-oracle.md`) labels fresh repositories' lock-file
   conflicts by the four computed actions only.** These are take local, take upstream, the
   package-level three-way merge, and the same unified. No tool runs, so no label depends on the
   registry's state on the day it is measured.
2. **Readers for every lock file study 1 counts.** npm (both files), pnpm, Pipfile, composer,
   Gemfile and uv join Cargo, poetry and yarn. Each is tested on its format. A file with
   conflict markers in it is read as nothing. `unify` follows each ecosystem's resolver:
   - a caret range where several versions can coexist (Cargo, npm, yarn, pnpm);
   - one version per package for the rest;
   - per platform for Ruby gems.
3. **Repositories count once.** Each figure is a mean of per-repository means, with a
   t-interval over repositories. In the pilot-based simulations (§8 of the registration), it
   supported H1 falsely less often than study 1's percentile bootstrap, though both were below
   3% at the bound. It also has a closed form a reader can check by hand.
4. **H1's bound is 0.10, from the power analysis.** At 15 repositories, 0.15 would have had power
   0.58.

## Consequences

**Gained:**
- A test of whether the lock-file task can have an external oracle, needing no API key, on
  repositories nobody here has looked at.
- Labels that study 2 or its successors can use without trusting this project's own rules.

**Accepted:**
- Cases where the maintainer's resolution came from running a tool count as uncovered, even
  where a tool run on that day would have reproduced them. The oracle is what can be computed
  today, and coverage is a lower bound on what an action-based labelling could reach.
- Uncovered conflicts are still labelled, by Jaccard per action. They can become "refuse" cases,
  but this study tests nothing about them.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Include the tool actions (`reconcile_*`, `regenerate`) | Today's registry is not the merge date's. In the pilot they failed on a third of runs and reproduced nothing extra. |
| Run the pilot's labelling on stage B's 161 cases instead | Those repositories were mined and their line labels seen. A confirmatory test needs repositories nobody has mined. |
| Bootstrap intervals, as studies 1 and 2 use | Valid here too, but less conservative at the bound in every simulated design (resampled pilot: 1.8-2.6% false support at the registered bound, against the t-interval's 1.0-1.6%), and not re-derivable by hand. |
| A 0.15 bound | Underpowered at the repositories the feasibility count found. |

## What would reverse this decision

H1 not supported with the study powered. That would mean computed actions label too few real
conflicts to be an oracle, and the lock-file task would need tool runs pinned to the merge's date
(a registry snapshot), or a different task.
