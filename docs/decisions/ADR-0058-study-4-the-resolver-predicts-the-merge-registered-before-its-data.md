# ADR-0058 — Study 4: whether the resolver predicts the merge, registered before its data

- **Status:** proposed
- **Date:** 2026-11-02
- **Supersedes:** nothing. It tests the exploratory finding of study 3 (ADR-0056,
  `results/lock-oracle-2026-11-02/`).
- **Deciders:** the author, working through the owner's queue; for the owner's review.

## Context

Study 3 found that a package-level three-way merge reproduces maintainers' lock files often, and
that unifying versions within it cut both ways. It helped where the resolver installs one version
of a package (composer, bundler, poetry). It hurt in npm's family, where compatible duplicates
coexist. That pattern was found after the data, on the same repositories it was found in.

## Decision

1. **Study 4 (`docs/preregistration/ecosystem-unify.md`) tests the pattern on fresh
   repositories.** Its unit is the discordant file, where the two merges disagree. Each repository
   votes once.
2. **The primary test pools both families.** In the power analysis, each family alone gets too
   few votes from 12–18 repositories: power 0.23–0.64. Pooled, H1 has 0.85 at 12 repositories and
   0.98 at 18. The per-family hypotheses are kept and decided, but the registration says they are
   not what the study is sized for.
3. **A sign test over repositories, not a t-interval.** Most repositories have no discordant file,
   so a mean over repositories of a difference in shares is mostly zeros. In simulation, a
   t-interval on it had power 0.57 at 20 repositories against the sign test's 0.99.
4. **Study 3's coverage is replicated as H4**, with study 3's own analysis and bound.

## Consequences

- **Gained:** the lock-file task's merge action can be fixed from a tested rule instead of an
  exploratory one, and study 3's headline gets a replication.
- **Accepted:** the hypothesis concerns only the files where the merges disagree. On every other
  file the choice makes no difference.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Test the per-ecosystem action's coverage against each merge's, over all cases | Mostly ties; power 0.57 at 20 repositories in simulation. |
| Per-family primary hypotheses | Too few votes per family at the feasible number of repositories. |
| Case-level McNemar test | Cases cluster within repositories. Contao alone gave 12 of study 3's 31 one-version discordant files. |

## What would reverse this decision

H1 not supported with at least 6 votes. The resolver's semantics would then not predict
maintainers' merges, and the task would need both merges as separate actions, chosen per case.
