# ADR-0009 — Build one library from the admit set, and dispatch every arm against it without writing to it

- **Status:** accepted (2026-09-30, as written)
- **Date:** 2026-09-30
- **Supersedes:** nothing (implements issue #4's central item; narrows spec §8's demotion and quarantine to the online mode)
- **Deciders:** repository owner

## Context

Issue #4: *"The three-arm comparison varies more than the dispatch function … each arm
builds its own library online from its own episodes."* `run_benchmark` gave each arm an
empty `library-{arm}` directory and let it grow: a fallback compiled a new program, a
failed fire demoted one, and a second wrong fire quarantined one. The only arm-2-versus-
arm-3 number the harness could produce therefore came from **different libraries**.
Recording `library_hash` on every row (#64) made that visible but did not fix it.

The spec already names the intended shape. The smoke seeds are "the admit set", used to
"admit the programs"; phase 1's exit criterion is that "arms share one frozen library";
and #4 asks for a library "compiled offline exactly once and committed".

Three facts constrain how:

1. **The build must not depend on either dispatcher.** If the build dispatched while it
   ran, for example by running arm 3's episodes over the admit seeds, then which programs
   were compiled, and which were demoted before the comparison began, would reflect arm
   3's decisions.
2. **The online writes are per-arm state.** Demotion and quarantine change what an arm
   can dispatch next based on what *that arm* fired before. Against a shared artifact,
   letting them run would either leak one arm's history into another's or, with a copy
   per arm, recreate the per-arm libraries #4 exists to remove.
3. **The cost curve needs the online mode.** Claim 1's amortization figure is about a
   library that grows from compile on fallback. That is a different question from the
   dispatch comparison, and it is not removed.

## Decision

1. **`bench.build_library` builds the frozen library from the admit set.** Each
   `(fault, seed)` is solved by the agent against **its own empty scratch library**, so
   nothing is dispatched during the build. Its solution is compiled and gated by the same
   `admit` the online runner uses. Every program produced is copied into one root,
   together with its `history.jsonl`: admitted ones, and rejected ones as the
   `candidate`s they stayed. The build's episodes go to their own ledger, so the cost of
   building is recorded and never mixed into the comparison.
2. **The root is built once.** A root that already holds a program is refused.
   Documentation files are allowed, so the committed `library/` can be the root.
3. **`run_benchmark(frozen_library=...)` dispatches every arm against that one root and
   never writes to it.** A fallback is solved but not compiled. A failed fire is not
   demoted. A wrong fire is recorded on the row (`fired_variant`, `misfired`) but not
   counted toward quarantine. Every row carries the same `library_hash`, which is
   re-read after the last episode, and a change raises.
4. **A root with no admitted program is refused**, so a library that was never built
   cannot read as two arms that never fire.
5. **The online mode stays the default.** It is what the cost curve measures, and spec
   §8's demotion and quarantine apply there unchanged.

## Consequences

**Accepted:**
- In the frozen mode a program that mis-fires keeps firing. Its misfires accumulate on
  the rows instead of withdrawing it, so a bad program's mismatch counts every time it
  fires, not twice. That is the right reading for a dispatch comparison, where the
  question is how often each dispatcher picks wrong from the same library. It is
  different from what an online deployment would see.
- The admit set is four seeds per fault, so the frozen library is small and may not
  cover every resolution. An uncovered resolution means both dispatch arms fall back
  there, which is visible as coverage, not hidden.
- Building needs a model and an API key, so the committed library does not exist until
  someone with a key runs the build.

**Gained:**
- The arms now differ in their dispatch function alone, and a test pins it: every row
  of a frozen run carries one hash, and the files are unchanged afterwards.
- The artifact's contents cannot depend on either arm.

**New obligations:**
- The committed library is built by one recorded run (`bench.build_library`), and its
  hash and build ledger are cited wherever the comparison is reported.
- Rebuilding it is a new artifact and a new hash, never an edit.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Build by running arm 3 (or 2) over the admit seeds | Later seeds would dispatch against earlier programs, so the library's contents, and any demotions during the build, would depend on that arm's decisions. |
| A copy of the frozen library per arm, with online writes allowed | Recreates per-arm libraries after the first write, which is the defect #4 names. |
| Keep demotion and quarantine in the frozen mode | Makes what an arm can fire depend on its own earlier misfires, which is per-arm state again, and changes the shared artifact mid-comparison. |
| Replace the online mode entirely | The cost curve (Claim 1) is about a library that grows, and it would lose its subject. |

## What would reverse this decision

- Evidence that the comparison needs the online dynamics, for example if the claim were
  restated as "which dispatcher recovers faster from its own mistakes". That is a
  different claim, and it would get a new ADR.
- An admit set too small to cover the resolutions, so that most frozen-mode dispatches
  are fallbacks for both arms. That would argue for a larger build set, drawn from seeds
  outside tune and eval, not for reverting to per-arm libraries.
