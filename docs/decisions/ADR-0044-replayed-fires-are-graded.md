# ADR-0044 — Each dispatch arm's fires are replayed and graded (exploratory)

- **Status:** accepted
- **Date:** 2026-10-21
- **Supersedes:** nothing. It adds an exploratory stage beside Figure 1; the pre-registered
  episode stages are unchanged.
- **Deciders:** repository owner (asked to keep implementing).

## Context

Figure 1 grades a dispatch decision by its **choice**: whether the fired program's resolution is
one the state accepts. It does not say what running the program does. The README listed
"mis-fires that end in a wrong repository" as unmeasured, under "nothing at episode level". The
pre-registered episode stages need a model, because an arm hands its misses to the agent. A
fire needs no model: the program is in the committed library, and replay never calls one.

## Decision

1. **`bench.consequences` replays every fire of arms 3 and 2 on the eval pairs** of a committed
   library, with no model call.
   - The decisions are Figure 1's: arm 3's first accepted program, and arm 2's top-1 at the
     threshold where the primary report matched it to arm 3's coverage. Each run's threshold and
     arm-2 mismatch reproduce the committed report exactly.
   - Each (state, program) is replayed once, on a fresh build, and shared by every pair that
     fired it.
2. **A fault's state is graded by the episode loop's two clauses** (`bench.run._grade`): the
   recorded state is intact over the fault's change surface, and the fault's checker passes. The
   recorded state is read first, because a checker can raise on a repository whose recorded
   objects are gone. A checker that raises anyway is recorded as `ungradable`, not a crash.
3. **A fault-free state is graded by whether anything moved**: HEAD, the branch, both
   repositories' refs and the working tree's status. Nothing needed doing there.
4. **It is exploratory.** It measures fires only, so it has no per-pair success rate, no cost and
   no comparison of episodes. It may not stand in for the frozen benchmark.

## What it found

On the three committed libraries (`results/consequences-2026-10-21/`):

| | arm 3 | arm 2 |
| --- | ---: | ---: |
| fires on a fault's state | 563 | 241 |
| fixed | 536 | 147 |
| not fixed | 27 | 86 |
| nothing ran | 0 | 8 |
| fires on a fault-free state | 0 | 318 |
| of them, changed something | — | 0 |
| fires that lost a recorded commit or rewrote upstream | 0 | 0 |

- **A correct choice is not always a correct outcome.** All 27 arm-3 failures are in run 13,
  from two admitted programs that exit cleanly and pass their own postconditions while the
  checker refuses the result:
  - an `aside` body that moves tracked edits into `.local` copies. The content survives, but
    against the checker's convention. It was compiled from a solve the checker had refused.
  - a `keep_local` body whose awk filter drops upstream's pure insertions.

  Runs 11 and 12 had none.
- **Arm 2's mis-fires mostly do nothing; on a fault's state they mostly fail.**
  - No fire on a fault-free state changed anything.
  - On a fault's state, 86 of 241 left the fault in place or worse, for example a rebase stopped
    mid-conflict or conflict markers left in `deps.lock`.
- **Figure 1 grades by variant name.** 88 of arm 2's fires on a fault's state were another
  fault's program. One with a matching name counts as correct, which flatters the baseline.

## Consequences

**Accepted:** the stage reports per fire, and its correct-outcome figure comes from two programs
in one library. It is a finding about these libraries, not a rate.

**Gained:**
- The README's "mis-fires that end in a wrong repository" is now measured for fires.
- Admission has a measured blind spot: a program's own postconditions can pass on a state the
  checker refuses, and admission may not read the checker (issue #9).

**New obligations:** none on the registered stages. Whether admission should replay on more
states, or require postconditions that state the resolution's whole contract, is a question for
the owner, not decided here.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Grade with the checker first, as `_grade` orders it | A checker raised on a destroyed commit, which would have hidden the loss as `ungradable`. |
| Replay arm 2 at every threshold | The matched point is the one Figure 1's comparison is read at; other thresholds answer other questions. |
| Count a fault-free fire as harmless without replaying it | A body can commit or edit where nothing needed doing; the snapshot is what shows it did not. |

## What would reverse this decision

A replay graded differently from how the episode loop grades the same body on the same state.
