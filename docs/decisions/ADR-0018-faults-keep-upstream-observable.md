# ADR-0018 — Every fault keeps `upstream/main` resolvable, so every state can be fingerprinted

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing (settles the design choice raised on issue #4, 2026-09-14)
- **Deciders:** repository owner

## Context

`StateFingerprint.observe` reads the tracked upstream ref (`upstream/main`) for its
count and diff probes, and it raises if that ref is gone. Making `branch_renamed`
real (#38) exposed a consequence for issue #4. A fault that prunes or deletes the
tracked ref leaves a state with **no fingerprint**, and admission's negative side
needs a fingerprint for every negative sandbox. The comment on #4 named two ways
out:

- `observe` tolerates a missing ref and reports it as a field; or
- every injector keeps the ref resolvable.

It also said the choice belonged to this issue, not to each injector separately.
In the meantime the code has taken the second path: `branch_renamed` leaves the
stale remote-tracking ref in place, which is what a non-pruning fetch leaves, and
carries the rename in `branch`. Nothing stated that rule, though, and nothing
checked it over the states admission actually builds.

## Decision

1. **Every fault injector must leave `upstream/main` resolvable.** This is written
   on `FaultSpec.inject`, the method every injector implements. A fault whose story
   is a missing upstream branch leaves the stale tracking ref, as `branch_renamed`
   does, and records the change in another fingerprint field.
2. **It is enforced over admission's own universe.** `tests/test_one_free_variable.py`
   builds every state in `agents.compile.sampled_states()`: the clean sandbox plus
   one sandbox per distinct injected state of every fault, i.e. the states admission
   and the breadth cap use as negatives. For each one it asserts that the ref
   resolves and that `observe` returns.

## Consequences

**Accepted:** a fault cannot model a pruned upstream literally. If one is ever
needed, this ADR is what it has to reverse (see below).

**Gained:** `observe` stays strict. A missing ref is still an error rather than a
silently defaulted field, so a broken sandbox fails loudly instead of being
fingerprinted as a plausible state. The rule is checked against the exact set of
states that needed it.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| `observe` tolerates a missing tracked ref and reports `tracked_ref_missing` | It turns an infrastructure failure (a sandbox that lost its remote) into a normal-looking state. A precondition could then pass or fail on that state for the wrong reason. It would also add a fingerprint field that no current fault needs. |
| Leave it to each injector, unwritten | That is how it stood. The first injector that pruned the ref would find out only when admission raised on a negative sandbox. |

## What would reverse this decision

- A fault whose correct resolution depends on the tracked ref really being absent,
  where a stale ref would make the state lie about itself. `observe` would then need
  the tolerant form, with the missing ref as an explicit field, and admission would
  need to handle a state that has it.
