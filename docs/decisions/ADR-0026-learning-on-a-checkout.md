# ADR-0026 — Learn on a checkout by solving a copy, confirming with the user, and admitting through the harness gate

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It adds a learning path beside the harness one (ADR-0009's
  build); every measured library is still built only by the harness.
- **Deciders:** repository owner (asked for #188 to be built without waiting on each
  choice); recorded so each choice can be challenged

## Context

#181 made an existing repository something the library can dispatch and replay on. It
did not let the library **learn** there (#188). A program is compiled only from an agent
solve inside a sandbox `sandbox.create` built, and admitted only by `agents.compile.admit`,
which judges it entirely on harness sandboxes:

- **positive side:** the body, replayed, fixes freshly injected instances of the fault;
- **negative side:** the preconditions refuse a clean sandbox, every unrelated fault's
  states, and the same intent's sibling states, within the breadth cap.

A real chore differs in two ways that matter:

- **No injector built it**, so there is no `FaultSpec.check` to say whether a solve fixed
  it.
- **No label says which family it belongs to**, so there is nothing to tell admission
  which sandboxes to build.

Three facts constrain the design:

1. **A solve must not touch the user's repository.** #181's dispatch already works on
   copies (`checkout.snapshot`). A solve on a copy is reversible; a solve on the
   checkout is not.
2. **Model-authored git on a checkout reaches no real remote.** The owner chose this in
   #181 (spec revision 79), and #196 applied it to the agent: tool calls are screened,
   confined, and redirected so only the mirror is reachable.
3. **Measured libraries must stay harness-only.** Claim 2 and Claim 3 are measured on
   libraries whose every admission the harness decided (ADR-0009, ADR-0010). A program
   admitted partly on a person's word must not enter them.

## Decision

1. **The agent solves on a disposable copy of the checkout.** `checkout.snapshot`, with
   the agent's git confined and screened as in #196. The checkout is never the solve's
   working directory.
2. **The caller names the family** (`--fault diverged` or `--fault submodule_moved`). It
   is not inferred from the request: classifying a request by its text is arm 2's
   mechanism, and inferring the family would smuggle that mechanism into every learned
   program's admission.
3. **The user's confirmation is the ground truth for the real solve.** The user is shown
   what the solve did to the copy (the dry-run summary of #181: commits added, the
   working tree's status, which parts moved) and confirms that it is what they wanted.
   Nothing is compiled without that confirmation; it is the only judge a real chore has.
4. **Admission is the harness gate, unchanged, plus one checkout-side check.**
   - The compiled program must pass `admit` on harness sandboxes of the named family:
     the same positive side, the same three negative classes, the same breadth cap, the
     same declared-variant rule.
   - It must also **fire where it was learned**: on a fresh copy of the original
     checkout, its preconditions must all hold, and replaying it must satisfy its
     postconditions.

   A program that only fixes the user's repository, or only fixes the harness's, is not
   admitted.
5. **A learned program is marked.** `Provenance.learned_on = "checkout"`, omitted from
   the serialized form when unset, so every harness program and every recorded library
   hash is byte-identical to before. `bench.run` refuses a frozen library that holds a
   marked program.
6. **Learning writes only to the library the caller names.** That library is the user's;
   the measured libraries under a live run's output are never written by it.

## Consequences

**Accepted:**

- A learned program is held to the harness's standard as well as to the user's
  repository. A chore the harness's family does not model well can be solved and
  confirmed and still not admitted. That is the cost of keeping one meaning for
  "admitted".
- The user's confirmation is a person's judgement. It can be wrong, which is why it is
  never the only check (decision 4) and never enters a measured library (decision 5).
- Families are limited to the measured ones. A chore outside them cannot be learned
  until its family has an `IntentSpec` (#189–#191).

**Gained:**

- The library can grow from the chores a user actually meets, through a path where
  nothing irreversible happens before the user confirms.
- Every learned program has passed the same gate as a measured one.

**New obligations:**

- The learn command must show the solve's effect before asking. A bare "did it work?"
  is not the confirmation decision 3 means.
- Any later path that admits programs must set `learned_on` when it is not the harness.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| The intent's postconditions as the only check on the real solve | Postconditions are written by the compile step, so they would grade the program by its own claim, the circularity spec §8 avoids by grading with a separate checker. |
| Admit on the user's confirmation alone, skipping the harness gate | It would create a second meaning of "admitted", and a precondition set that fires on everything would pass. |
| Infer the family from the request text | That is text-similarity dispatch, the mechanism Claim 2 compares against, inside the learning path. |
| Solve on the checkout itself and roll back on decline | A rollback cannot undo everything a solve might do (hooks are off, but ref logs, stashes and remote-tracking refs move). A copy needs no undo. |

## What would reverse this decision

- If confirmed, harness-admitted learned programs are often demoted on the user's later
  chores, the harness gate is not transferring to real repositories, and the
  checkout-side check needs to carry more weight than the harness's.
- If the harness gate rejects most confirmed solves, the families model real chores too
  narrowly, and the families (#189–#191), not this ADR, need changing first.
