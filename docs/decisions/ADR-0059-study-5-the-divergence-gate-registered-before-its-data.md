# ADR-0059 — Study 5: the divergence gate, registered before its data

- **Status:** proposed
- **Date:** 2026-11-08
- **Supersedes:** nothing. It tests the exploratory finding of `results/lock-anatomy-2026-11-04/`,
  made on studies 3 and 4 (ADR-0056, ADR-0058).
- **Deciders:** the author, working through the owner's queue; for the owner's review.

## Context

After seeing studies 3 and 4, the anatomy of their conflicts showed two things.

- A conflicted lock file's per-ecosystem merge mostly reproduces the maintainer when no package
  *diverges*, meaning both sides changed its versions, to different versions. It mostly fails when
  one does.
- A rule over the three sides alone, "fire the merge only if no package diverges, else refuse",
  cut the merge's case-level mismatch from 0.56 to 0.32 in study 3, and from 0.45 to 0.22 in
  study 4. Both are still well above study 1's 0.10 for "rarely mis-fires".

The report states both as hypotheses. The second is also the report's answer to its own question
for this task: an executable precondition helps, but does not make the merge rarely wrong.

## Decision

1. **Study 5 (`docs/preregistration/divergence-gate.md`) tests the rule on fresh repositories.**
   It uses study 3's cases and labels, study 4's predicted merge, and the anatomy's definition of
   divergence, all fixed in code before mining.
2. **The primary hypothesis is that the gate is still not rarely wrong (H1).** The test is the
   mean over repositories of the gate's mismatch, with a lower bound above 0.10. It is the
   report's conclusion, and the hypothesis the study is best powered for: 0.85 at 20 repositories.
3. **That the gate lowers mismatch is H2, and it is disclosed as largely structural.** In npm's
   family the plain merge keeps both sides' versions of a divergent package, and maintainers
   almost never do. The gate is therefore near-certain to help there. H2's power is 0.85 at 20.
4. **H3 isolates the one-version family, where divergence does not defeat the merge by
   construction.** It is the hypothesis that could most plausibly fail. Its statistic is a
   within-repository Mantel-Haenszel risk difference, and the registration states its low power
   (0.37 at 20 repositories).
5. **Repositories are chosen from a feasibility count that records which family's lock files
   conflict.** It still reads no merge commit's tree. This lets the list favour repositories with
   one-version conflicts, which H3 needs.

## Consequences

- **Gained:** the report's dispatcher conclusion for real lock-file conflicts gets a
  confirmatory test, and the anatomy's mechanism gets a replication.
- **Accepted:** H3, the least structural test, is underpowered at any feasible size. The
  registration says so before the data, and a failure of H3 is reported as uninformative unless
  its interval excludes the exploratory estimate.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| H3 as the per-repository mean of m_always − m_gate on one-version cases | Dilutes the contrast by each repository's share of divergent cases; power 0.20 at 20 repositories in simulation. |
| H3 as the pooled difference, over all cases, between reproduction without and with divergence | Confounded by repository. Repositories that diverge often also reproduce less, so under a null with no within-repository effect it was "supported" 17–51% of the time. |
| The gate's lowered mismatch as the primary hypothesis | Largely structural in npm's family, as point 3 says. A primary hypothesis should be one the data could plausibly refute. |
| A larger per-repository cap than study 3's 15 | The power analysis cannot simulate it from studies 3 and 4, which hold at most 15 cases per repository. |

## What would reverse this decision

H1's interval lying wholly below 0.10. The gate would then make the merge rarely wrong on
repositories nobody here had seen, and the report's conclusion about dispatch on real lock-file
conflicts would be wrong.
