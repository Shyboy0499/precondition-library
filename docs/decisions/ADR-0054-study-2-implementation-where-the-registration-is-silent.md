# ADR-0054 — Implement study 2 as registered, and fix in advance what the registration leaves open

- **Status:** proposed
- **Date:** 2026-10-30
- **Supersedes:** nothing. It implements ADR-0053 and `docs/preregistration/refusal-population.md`
  §4 step 2, which asks for the study's code to be reviewed before any build.
- **Deciders:** the author proposes; the repository owner accepts or changes it by reviewing the
  pull request that adds it, before any of R is mined.

## Context

The registration fixes the hypotheses, the lists, the sizes, the statistics and the decision rules.
Writing the code met six places where it does not say exactly what to do. Each has to be decided
before any data exists, or the choice could be made with the data in view. No case of R or of the
evaluation set has been mined, and no build has run.

## Decision

1. **The refusal rule is part of the two-sided gate, checked last.** Under configuration R,
   `admit` checks R's states only after the clean, unrelated, sibling and breadth checks pass,
   because R's states are real repositories and the most expensive to build. A program whose
   preconditions all hold on any state of R is refused. A probe that cannot be evaluated there (a
   placeholder outside the vocabulary, a probe the guard refuses) refuses the program, as on the
   negative side.
2. **A program R refuses gets the same one revision as any refused program** (ADR-0030), shown the
   R states it fired on as observed. §5 says configuration R differs from 0 "in the rule, and in
   what follows from it"; the revision is what follows from any refusal under the committed gate.
3. **R's states are rebuilt for every program checked, and each is compared with its frozen
   observation the first time.** Forty real checkouts do not fit beside a build, so none is kept. A
   state that no longer rebuilds as frozen stops the build: a configuration R library must be gated
   by the set the registration froze. `build.json` records the frozen set's SHA-256.
4. **The 25% cap is 25% of the targets' sum.** §3.4 says no repository may contribute more than
   25% of the cases, while the number of cases is not known until mining stops. Study 1 took 25% of
   its target. Here the targets are 100 inexpressible and 60 clean cases, so the cap is 40 cases,
   and past it a repository keeps its most recent, conflicted and clean in equal number, by study
   1's `_capped`.
5. **The stopping rule is checked between repositories.** A repository is mined whole, then the
   targets are checked, as in study 1. Mining never stops part-way through a repository.
6. **Reported beside the intervals, without deciding anything:**
   - a build "individually beats the control" when its own margin's repository-clustered
     interval lies above 0;
   - how many of R's states have exactly the features of one of the 56 training states.
     Control-R cannot tell such a state apart from the training state, and predicts the label
     those identical rows hold more often (`StateClassifier.fit`). The count is reported. Nothing
     is dropped or reweighted, because §6 fixes the fit.

## Consequences

**Accepted:**

- Rebuilding R for every candidate costs time: up to 40 checkouts of four large repositories per
  program that reaches the refusal side. The time is measured when R is mined. If it is
  prohibitive, a change before the first build may keep some states built, as long as the gate's
  verdicts stay the same.
- Revisions shown R's states let a revised program learn from R. That is the evidence
  configuration R is meant to have, and Control-R gets the same states.

**Gained:** every choice above is fixed and reviewable before any data exists. Each is tested:
`tests/test_refusal_admission.py`, `tests/test_refusal_set.py` and `tests/test_refusal_study.py`.

**New obligations:** the results report states the time R's checks took, the collision count, and
any replacement build (indices 10, 11 and 12) with its reason.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Check R before the negative side | R is the costliest check; any program the cheaper checks refuse would pay for it for nothing. |
| No revision after an R refusal | Configuration R would then differ from 0 in two rules, the refusal and the revision, against §5. |
| Keep R's forty states built for the whole build | Forty checkouts of matomo, saleor, openfoodnetwork and Rocket.Chat would not fit on the disk beside a build. |
| Cap at 25% of the cases mined so far | The cap would move as mining went on, and the first repository could never be capped. |
| Drop or reweight R's states that collide with training states | §6 fixes Control-R's fit as the 56 states plus R. Changing it would need an amendment, not code. |

## What would reverse this decision

- The owner's review of the pull request, before R is mined, choosing differently on any item.
- R's checks taking too long to run twenty builds. That would change item 3's mechanism, not its
  verdicts.
