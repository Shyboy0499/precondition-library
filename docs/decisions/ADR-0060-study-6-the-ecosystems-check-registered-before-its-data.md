# ADR-0060 — Study 6: the ecosystem's check, registered before its data

- **Status:** proposed
- **Date:** 2026-11-09
- **Supersedes:** nothing. It tests the exploratory findings of
  `results/lock-tool-check-2026-11-08/`, made on studies 3–5 (ADR-0056, ADR-0058, ADR-0059).
- **Deciders:** the author, working through the owner's queue; for the owner's review.

## Context

#297's second oracle, each ecosystem's own consistency check, was run on studies 3–5's
conflicted `composer.lock`, `package-lock.json` and `pnpm-lock.yaml` files after the studies
were seen. It found:

- **Merges break lock files.** Merged files fail the check far more often than ordinary commits'
  lock files fail it in their own trees: 0.14 against 0.03.
- **A dispatcher of two executed checks.** Study 5's divergence gate, then "take the one side
  the check accepts", covers far more than the gate alone at about the same error: 0.69 against
  0.40 of files, at mismatch 0.32 against 0.28.
- **A tie-break that never lost.** Against taking the first parent's file it won on 20 files
  and lost on none, which is what the check's structure predicts.

The first is a finding about the task itself: it says why automating lock-file conflict
resolution with a check is worth doing. The second is the project's thesis, a precondition that
is run rather than guessed, applied to real data. Both were found after seeing the data.

## Decision

1. **Study 6 (`docs/preregistration/tool-precondition.md`) tests them on fresh repositories.**
   It reuses studies 3–5's mining, labels, divergence and predicted merge. The checks are made a
   library (`bench.lock_check`), the code the exploratory run used. The study's module reproduces
   every exploratory figure before any new data is mined.
2. **The primary hypothesis is H1: merges leave lock files inconsistent more often than ordinary
   commits.** It is the finding that most changes what the project says about the task, and it
   could fail. Power is 0.95 at the registered 25 repositories, and 0.89 at 20.
3. **H2 holds rule D to study 1's bar, "rarely mis-fires" (0.10).** Like study 5's H1, it is
   expected to be supported. It is registered so that the best rule so far is tested, not just
   reported.
4. **H3 states the tie-break's structural property as a bound:** the reverse share's Wilson
   upper bound is below 0.10. Its gain over the first parent's file is reported, not tested,
   because it is concentrated (12 of 20 exploratory wins in one repository). A mean-over-
   repositories test of it had power 0.25.
5. **Mining keeps only cases whose conflict includes a checked lock file, and leaves out those
   where a conflicted one has a `merge` attribute at the first parent.** Both happen before
   study 3's cap of 15, so neither takes a place. The second follows
   `results/mining-attributes-2026-11-08/`'s recommendation for the next registration.
6. **The checks run only the tools the owner approved:** npm, pnpm (at the declared version)
   and Composer, with install and lifecycle scripts off. Yarn, Cargo, Poetry and Bundler are out
   of scope.

## Consequences

- **Gained:**
  - a confirmatory test of a finding about the task itself;
  - the first registered test of a dispatcher built from two executed checks on real
    conflicts;
  - a mining rule that reads attributes as a maintainer's working tree does.
- **Accepted:**
  - The study covers three lock-file kinds of the ten studies 3–5 read.
  - Its repositories are skewed to PHP and JavaScript applications that merge long-lived
    branches, because they are where such conflicts occur.
  - npm and pnpm read registry metadata, so the checks need network access, though their
    verdicts do not depend on the registry's state.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| H3 as the tie-break's gain, the mean over repositories of (accepted side right − first parent's right) | Power 0.25 at 20 repositories in simulation: the exploratory gain sits in a few repositories. |
| H3's bound at 0.05 | Its power depends on how many tie-break files the mining yields: 0.88 at 25 repositories, but 0.60 at 20 and 0.20 at 15, because zero reverses among about 77 files leave the Wilson upper bound near 0.05. A bound that fails for want of files says nothing. The 0.05 reading is reported as a description. |
| H1 pooled over files rather than per repository | Files cluster in repositories, and a few repositories with many failing merges would carry it. The per-repository mean is the analysis studies 3–5 used. |
| Counting a case whose only conflicted lock files are unchecked (yarn, Cargo, ...) | It would take a place under the cap and give no figure. |
| Running the projects' tests as a further oracle | It executes the projects' code, which the owner did not approve (#297). |

## What would reverse this decision

- **H1's interval lying wholly below 0, or including 0 with a small mean.** Merges would then
  not be where lock files break, and the exploratory gap would have been the studies' sample.
- **H3 not supported.** The check's tie-break would then lose to "take your own branch" often
  enough to matter, and rule D's second step would need another check.
