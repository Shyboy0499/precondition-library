# ADR-0014 — The gold baseline is a ground-truth oracle, and that is what makes it a floor

- **Status:** accepted (2026-10-01)
- **Date:** 2026-10-01
- **Supersedes:** nothing (first of issue #7's four baselines)
- **Deciders:** repository owner

## Context

Issue #7 asks for four baselines so an arm-3 win is attributable rather than a
straw man, and the last of them is "hand-written gold scripts as a zero-token
oracle floor". The repository already carries those scripts: `bench/gold/`
holds, for each measurable fault, one hand-written resolution per state the
fault can inject, written and checked by a human before any agent result was
believed (the spec's gold-first rule). What issue #7 adds is an **arm** that
runs them, so the benchmark has a floor that bounds success from above (what is
reachable at all on this task family) and cost from below (zero LLM tokens).

The design places a hard rule on every other arm: the arm decides when it is
done, and the fault's checker is consulted only afterwards, so no arm is handed
an oracle arm 1 was denied (issue #9, `bench.run`). A gold "oracle floor" is a
deliberate exception to exactly that rule — to pick *which* gold resolution to
run, it reads the state's ground-truth variant. The decision to record is
whether that exception is legitimate, and how to keep it from contaminating the
comparison it sits beside.

## Decision

1. The gold arm (`Arm.GOLD`) is an **oracle**: for each episode it looks up the
   ground-truth variant (`IntentSpec.correct_variant`) and replays that
   variant's hand-written gold program, making **no model call**. It never falls
   back to the agent and never compiles — a floor that quietly called the model
   would no longer be a zero-token floor — so a gold replay that fails is
   recorded as a failure rather than paid for again.
2. Because it consults ground truth, the gold arm is **a floor, not a
   dispatcher**, and is **excluded from the matched-coverage dispatch
   comparison** (the primary metric, `bench.coverage` / `report.mismatch_comparison`,
   which read only arm 2 and arm 3). It appears in the per-arm cost and success
   tables and on the Pareto frontier, where a floor belongs: the cheapest,
   highest-success point the other arms are read against.
3. The oracle cannot misfire — it fires the ground-truth variant by
   construction — so its `fired_variant` is that variant and its mismatch rate is
   zero by definition, which is a fact about an oracle and not a measured win.
4. `run_benchmark` checks **up front** that the gold set covers every measured
   fault's every variant (`_require_gold_covers`), refusing the run otherwise.
   A missing resolution would otherwise surface mid-run as a zero-spend failure
   that reads like a gold program that could not run, rather than as the gap in
   the oracle it actually is.
5. The gold programs stay repository fixtures in `bench/gold/`, loaded by
   `bench.gold.load_gold_programs` and **injected** into the run the way the
   `provider` and the `similarity` seam are, not reached for from deep in the
   run loop.

## Consequences

**Accepted:** one arm in the ledger is allowed to see ground truth, which is a
real exception to the no-oracle rule the rest of the harness depends on. The
mitigation is that the exception is total and visible — the gold arm is the only
arm `bench.run` hands the correct variant, it is named an oracle everywhere it
is reported, and it is kept out of the comparison whose integrity the no-oracle
rule protects. Its numbers answer "how good could an arm be here, and how cheap",
not "did preconditions beat similarity".

**Gained:** a ceiling and a cost floor the other arms are read against. A success
rate well below gold's says the task family has headroom no arm reached; a cost
far above gold's zero is the price of not having the answer written down. Both
are context the three-arm comparison cannot provide on its own.

**New obligations:** the gold set must stay complete as faults or variants are
added, or a gold-arm run is refused until it is — which is the intended failure,
not a regression. The gold scripts are also the pre-registered correctness
reference for the compiled library, so a change to them is a change to that
reference and belongs in a PR against the fixtures with its own justification.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Gold selects its resolution by its own preconditions, like arm 3, instead of by ground truth | Then it is not an oracle and not a floor — it is a second precondition arm over hand-written programs, which measures predicate authorship, not the ceiling. The floor's whole value is that it knows the answer. |
| Let the gold arm fall back to the agent when a replay fails | Destroys the zero-token property that makes it a cost floor: a single fallback charges it the agent's tokens, and the floor stops bounding cost from below. A gold replay failure is recorded instead, and is itself informative. |
| Put the gold arm in the matched-coverage comparison | It fires on every state (it always has the answer) and never misfires, so it would enter the comparison at full coverage with zero mismatch — an oracle's artefact read as a dispatch result, the exact confound the comparison is matched to avoid. |
| Ship the gold scripts as package data instead of repository fixtures | They are shared with the test suite, which loads the same directory; duplicating them into the package would create two sources of the correctness reference that could drift. The repository is run from its source tree, as its own CI is. |

## What would reverse this decision

- A compiled library good enough to serve as the correctness reference would
  make the hand-written gold scripts redundant as the oracle; the floor could
  then be the best admitted program per state rather than the hand-written one.
- If a later design removed the no-oracle rule for the compared arms (for
  instance, by giving every arm a verifier), the gold arm would no longer be an
  exception and this ADR's central tension would dissolve — though a zero-token
  floor would still be worth reporting.
