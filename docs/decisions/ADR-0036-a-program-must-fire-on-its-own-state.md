# ADR-0036 — A program's preconditions must hold on its own positive states

- **Status:** accepted
- **Date:** 2026-10-12
- **Supersedes:** nothing. It adds one check to admission's positive side (`agents.compile.admit`).
- **Deciders:** repository owner, after the abstention diagnosis in `results/abstentions-2026-10-12/`.

## Context

Admission is two-sided. The **positive side** replays the program on freshly faulted sandboxes: the
body runs, and the postconditions must hold. The **negative side** refuses preconditions that accept
a clean sandbox, an unrelated fault's state or a sibling resolution's state. The breadth cap refuses
preconditions that accept too much.

Nothing refused preconditions that accept **nothing**. A program whose preconditions never hold
passes every side: its replay works, because a replay runs the body without asking the
preconditions, and it refuses every negative, because it refuses everything. It is admitted, and
then it can never fire.

**Evidence.** `results/abstentions-2026-10-12/` found one such program among the 40 admitted in the
three committed libraries: replicate 2's `lockfile_conflict-occ2-lockfile-merge-keep-local-removals`.
Its `three_way_merge_conflicts` probe calls `git merge-file` on process substitutions, which git
2.43 reads as empty, so the preconditions fail on every `keep_local` state, including seed 2, the
state it was learned on. It accounts for all 13 of arm 3's misses in that library. The evidence is
one program in one family, but the gap is structural: any program with an unsatisfiable
precondition is admitted the same way.

## Decision

1. **On the positive side, each positive seed's fresh sandbox must satisfy the program's
   preconditions** (`runtime.probes.evaluate_preconditions`, the evaluator arm 3 dispatches with)
   **before the body is replayed there.** If they do not hold, the program is refused with
   `positive side failed on <fault> seed <seed>: the preconditions do not hold on the state the
   program is meant to fix`, plus the failing predicates.
2. **Both gates.** The check is part of the positive side, so `AdmissionGate.POSITIVE_ONLY` runs it
   too. The admission factorial's two cells still differ only in the negative side (ADR-0010).
3. **The same sandbox.** Probes only read (a probe that changes the sandbox is refused, issue #10),
   so they run on the fresh sandbox the replay then uses. No extra sandbox is built.
4. **The refusal is revisable.** It is an ordinary positive-side refusal, so the compile's one
   revision (ADR-0030) is shown its reason.

## Consequences

**Accepted:** one precondition evaluation per positive seed, on a sandbox that is already built.
Builds made before this change can contain dead programs. The three committed replicate libraries
are not rebuilt, and their figures stand as measured: a dead program never fires, so it cannot
mis-fire, and it costs only coverage, which Figure 1 already reports. A future build may admit
fewer programs, but none it drops could ever have fired on its own state.

**Gained:** "admitted" now implies "fires where it was learned". Arm 3's coverage can no longer be
lost to a program the gate passed but that could never run.

**New obligations:** none for the prompt, which already says preconditions must describe the state
the program fixes. A test pins the refusal under both gates.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Require the preconditions to hold on **every** state of the program's own resolution, not only the positive seeds | That is a generalisation test. Run-13's narrow checks would fail it, but it needs more sandboxes per admission and a decision about which instances count. Admission's job is to refuse programs that are wrong; a program that is merely narrow mis-fires on nothing. Left to the held-out work (#263). |
| Check after the replay, on a second fresh sandbox | It costs a sandbox per seed and buys nothing, because probes only read. |
| Leave admission alone and filter dead programs at dispatch | A dead program never fires, so dispatch already ignores it. The cost is the coverage it was meant to provide and the revision it never got. Only admission can send it back. |

## What would reverse this decision

A legitimate program whose preconditions must *not* hold on the state it was learned on, or a
repository state where evaluating the preconditions before the body changes what the body does.
Neither exists in the task family, and the probes' read-only guard rules out the second.
