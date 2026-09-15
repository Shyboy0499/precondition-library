# Decision records

One file per decision that is expensive to reverse: a change to the claims, the
experimental design, or the architecture. The point is that a reader two years
from now can see *why* the repository looks the way it does, including the
alternatives that were rejected — a rationale that exists only in a chat log or a
commit message is not a record.

| ADR | status | decision |
| --- | --- | --- |
| [ADR-0001](ADR-0001-reframe-after-prior-art.md) | accepted | Re-center the project on the open measurement. Claim 1 dropped as prior art; Claim 2 narrowed to its empirical form; the primary metric moved to matched dispatch coverage. |
| [ADR-0002](ADR-0002-similarity-dispatch-is-lexical.md) | accepted | Run arm 2 as deterministic lexical text similarity behind a `Similarity` seam, with an embedding model as the intended replacement. The claim compares preconditions against *text* similarity, not embeddings. |

## When to write one

Write an ADR when you:

- reverse or narrow a previously stated claim or decision;
- change what the experiment measures, or what counts as a result;
- adopt a dependency, a domain, or a measurement approach that constrains later work;
- decide *not* to do something that a reader would reasonably expect (record why).

Not needed for: clarifications that change nothing measurable, typo fixes, or
adding a fault to the task family — that last one is a normal design change and
belongs in a PR against the spec.

## Statuses

`proposed` — under discussion, not yet binding.
`accepted` — in force. Superseding it requires a new ADR.
`superseded by ADR-XXXX` — kept for the record, no longer binding.
`rejected` — considered and declined; keep it, because the reasoning is the value.

## Format

Copy [`TEMPLATE.md`](TEMPLATE.md). Two sections carry most of the weight:

- **Alternatives rejected** — each with the reason. A record with no rejected
  alternative is usually a record of a decision that was never actually weighed.
- **What would reverse this** — the evidence that would overturn it. A decision
  that cannot be reversed by any observation is a belief, not a decision.
