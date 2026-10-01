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
| [ADR-0003](ADR-0003-arm2-baseline-scope.md) | accepted | Quote arm 2's baseline per intent over the whole ambiguous subset (pooled AUC 0.5722 and strict top-1 23/48; 0.4778–0.7264 across the two intents) and keep the lexical seam: IDF weighting and dropping the constant `intent` both fail to improve strict top-1, which is what dispatch acts on. |
| [ADR-0004](ADR-0004-arm2-baseline-is-the-informed-regime.md) | accepted | Quote arm 2's baseline on the **informed** request regime (AUC 0.6172, strict top-1 15/24 = 63%; hand-written gold on probe seeds 0–3, not the pre-registered split) and report the uninformed regime beside it as the plumbing tripwire, which is chance by construction and holds the negative pairs. Narrows ADR-0003's baseline scope; ADR-0003 stays accepted and its pooled figures stay on the record. |
| [ADR-0005](ADR-0005-instance-diversity.md) | accepted | Parameterise each injected state along **declared axes** drawn per seed, so a new seed is a new environment rather than the same shape with different SHAs; key occurrence roles on **instance identity** rather than resolution; restate the seed plan in terms of independent environments and carry the achieved instance count in the report. Measured today: the two measurable faults offer 3 content-distinct environments each, 6 across the family. Scopes #86 without changing any injector. |
| [ADR-0006](ADR-0006-init-instances-and-the-equivalence-margin.md) | accepted | Count `submodule_moved/init` as five environments, witnessed by the nested content its gitlink names rather than the gitlink's commit id (61 plan / 47 eval stand). Keep the ±10pp equivalence margin, and state its power as the TOST on a difference: ±16.5pp at 47 per arm and a 50% rate, first passable at 133 per arm, so the expected verdict is "comparable". Settles the two questions #86 left to the owner. |
| [ADR-0007](ADR-0007-arm2-baseline-floor.md) | accepted | Arm 2 counts as the baseline only if its informed-regime strict top-1 on the tune set, against the eval library, clears chance (1/3) by its **95% Wilson lower bound**; below it the comparison is still reported but "preconditions beat text similarity" may not be stated. Closes #116's last open item. |
| [ADR-0008](ADR-0008-mismatch-coverage-definitions.md) | accepted | Define the primary metric's arithmetic: arm 2's threshold is swept over every distinct score, arm 3 (no score) is **one operating point whose coverage is the pre-registered coverage point**, and mismatch is **wrong fires over fires**, a fire on a negative pair counting as wrong. Matched coverage is arm 2's nearest point, ties to the lower coverage, gap reported; regimes are never pooled; the comparison is reported as vacuous while arm 3 decides every pair correctly. |
| [ADR-0009](ADR-0009-one-frozen-library.md) | accepted | Build **one** library from the admit set with `bench.build_library` -- each seed solved and compiled against its own empty scratch library, so nothing is dispatched during the build -- and dispatch every arm against it with `run_benchmark(frozen_library=...)`, which never writes to it: no compile on fallback, no demotion, no quarantine; every row carries one `library_hash`. The online per-arm mode stays for the cost curve. Implements #4's central item. |
| [ADR-0010](ADR-0010-admission-factorial.md) | accepted | Run the {dispatch} x {admission} 2x2 as **one compile gated twice**: "ungated" is `AdmissionGate.POSITIVE_ONLY` -- identical to the two-sided gate except the negative sandboxes are skipped -- built into a second frozen root; each root's `build.json` names its gate, every row records `admission_gate`, and `report.admission_factorial` gives one cell per (arm, gate). Arm 3-prime is the {precondition, positive-only} cell. |
| [ADR-0011](ADR-0011-arm2-rerank.md) | accepted | Give arm 2 an optional **top-k rerank**: `Library(reranker=..., rerank_k=3)` -- the first-stage `Similarity` retrieves the top k, a second `Similarity` rescores them, and the reranker's score is what the threshold judges and the row records. No LLM call, so arm 2's replays stay free; the reranker is metered as `embedding_*` and rows record `rerank_k`. Default off. |
| [ADR-0012](ADR-0012-replicates-and-cluster-bootstrap.md) | accepted | Repeat the plan as **whole-run replicates** (`run_replicates`, k = 3, each with its own ledger and online libraries; rows record `replicate`), and take #6's seed-level uncertainty from an **instance-clustered bootstrap** (`report.cluster_bootstrap`: whole instances resampled with all their arms and replicates, seeded, 2000 resamples) instead of fitting a mixed model. |
| [ADR-0013](ADR-0013-isolation-is-a-runner-requirement.md) | accepted | The library enforces only the isolation a process can give itself (process-group kill, POSIX rlimits, a network namespace where the host grants it, plus the non-privilege defences); the remaining #10 items — a separate **unprivileged user** and a real **disk quota** — are a **runner requirement** the execution container must provide, recorded in `docs/running-unattended.md`. The library records `network_isolated` but does not verify the user or the quota. |

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
