# ADR-0050 — Rebuild the research layer from real merges; keep the harness

- **Status:** accepted
- **Date:** 2026-10-27
- **Supersedes:** nothing yet. It sets the direction #306 and #307 implement, and those will
  supersede parts of ADR-0029 (the lock-file intent's resolutions) and ADR-0032 (one build per
  replicate) when they land.
- **Deciders:** repository owner ("Full rebuild", 2026-10-27).

## Context

Three findings from the real-merge work, each from data this project did not label:

1. **The tasks were invented.** No maintainer's lock-file merge is either of the intent's line
   unions (stage A: 0 of 30). Read package by package, a third have a reproducible answer, and
   the best single action is the package-level form of the intent's own idea
   (`results/lock-actions-2026-10-27/`: 10 of 30, `three_way_unified` 6). The formulation, not
   the idea, was wrong. And 27 of the 30 conflicts are not lock-only.
2. **"Precondition dispatch" is whichever library got built.** On the same 30 real conflicts,
   run 12's library refused all 30 and run 13's fired on all 30 (stage A under Amendment 1,
   exploratory). Three builds cannot separate the method from the build.
3. **The distinctive property is refusal, and nothing selects for it.** On synthetic labels,
   reading the state matches executable checks (ADR-0047). On real states, the state reader
   fired on every conflict while one library refused every one.

The harness, by contrast, has now been tested from outside its own design. It produced these
findings: 1,954 tests; 600 generated states with no grader or gold defect; and a mutation run
that found one real grader defect, now fixed (#299).

## Decision

**Rebuild the research layer: what the tasks are, how libraries are built, and what the
headline claims. Keep the harness.**

1. **Tasks from observed practice (#306).**
   - A lock-file resolution is judged on its `(package, version)` set, never its lines.
   - The action set is what maintainers do: take a side, merge package by package (with and
     without unification), or reconcile with the ecosystem's tool.
   - Real cases are labelled by which actions reproduce the maintainer.
2. **Libraries as a population (#307).**
   - At least 10 builds per configuration.
   - Admission also requires refusing real out-of-distribution states.
   - Every figure is a distribution over builds.
   - This needs an API key, which the owner provides through the environment's settings.
3. **Study 2 is registered before its data is mined.** It covers the package-level labels, the
   build population, and refusal as the primary endpoint.
4. **The headline is rewritten last (#300)** to what survives, with external results first.

## Consequences

**Accepted:**
- The synthetic Figure 1 stays committed and reproducible. It moves to the "on this project's
  own labels" tier.
- The lock-file intent will change. Its committed libraries stay as they are, as the record of
  the old formulation.

**Gained:** a research question whose answer this project cannot have written: does executable
dispatch refuse the real states it does not fit, across builds, more reliably than reading the
state?

**New obligations:**
- No figure on real data is drawn from one build.
- Every new action is labelled from what maintainers did, not from a rule written here.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Rewrite the harness too | It is the part that is tested from outside, and it is what produced these findings. |
| Keep the toy tasks and only add real data | Stage A showed the toy action space reproduces none of the real cases. |
| Measure more synthetic replicates | They cannot answer whether the method transfers; only real states can. |

## What would reverse this decision

Study 2 finding that, across builds, arm 3 refuses inexpressible real states no more often than
the state-reading control. The method's claim would then reduce to ADR-0047's, and the
rebuild's outcome would be to say so.
