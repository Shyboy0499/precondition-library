# ADR-0012 — Repeat the plan as whole-run replicates, and take seed-level uncertainty from an instance-clustered bootstrap instead of a mixed model

- **Status:** proposed
- **Date:** 2026-09-30
- **Supersedes:** nothing (narrows issue #6's "mixed model keyed on fault seed" to a cluster bootstrap; ADR-0005's unit of analysis stands)
- **Deciders:** repository owner

## Context

Issue #6 asks for **k ≥ 3 repeats per (fault, seed, arm)** and an analysis that "uses a
mixed model keyed on fault seed (seed as random effect), reporting seed-level
uncertainty". Neither existed. Each (fault, seed, arm) ran once, and the report's
intervals were Wilson intervals over rows.

Repeats need a definition, because the online mode learns. If an episode is repeated
back-to-back inside one run, the second repeat finds the program the first one
compiled. It is then a replay, not a repeat, and the repeats are not independent of
each other.

A mixed model needs a fitting library. This repository deliberately depends on no
statistics package (`bench.report` implements Wilson and TOST in the standard library
rather than import SciPy). A binomial GLMM such as statsmodels' would add a heavy
dependency for one number. With 47 eval instances, a fit is also prone to
convergence failures and variance estimates on the boundary.

What #6 actually needs from the model is **seed-level uncertainty**: an interval that
knows rows from one instance are not independent. Since ADR-0005 the instance, not the
bare seed, is the unit.

## Decision

1. **Repeats are whole-run replicates.** `bench.run.run_replicates(out_dir, replicates=3,
   ...)` runs the whole plan `replicates` times. Replicate `r` writes
   `out_dir/replicate-r/ledger.jsonl` and, in the online mode, grows its own per-arm
   libraries beside it. So no replicate starts from another's programs. A frozen library
   is shared, because it is read-only. The default is `DEFAULT_REPLICATES = 3`, which
   is #6's k.
2. **Rows record `replicate`.** The field defaults to 1 and is written on normal and
   invalid rows alike.
3. **Seed-level uncertainty comes from `bench.report.cluster_bootstrap`.** It resamples
   **instances** (fault plus `instance_for_seed` identity) with replacement. Each
   instance carries all its rows across both dispatch arms and every replicate. The
   estimate is arm 2's per-fire mismatch minus arm 3's (ADR-0008), with a percentile
   interval. It uses `BOOTSTRAP_RESAMPLES = 2000` resamples, a fixed `BOOTSTRAP_SEED`,
   and 95% confidence. It reads graded variant rows only, as `mismatch_comparison`
   does, and it skips and counts any resample in which an arm fired nothing, rather
   than scoring it.
4. **No mixed model is fitted.** The bootstrap stands in for #6's mixed model, and this
   ADR is the record of that substitution.

## Consequences

**Accepted:**
- A cluster bootstrap estimates uncertainty but not the variance components. It says
  how wide the interval is once instances are resampled. It does not say how much of
  the variation is between instances rather than within them.
- With few instances the percentile interval is itself rough, and at the episode
  loop's size it stays underpowered, as ADR-0006 already says.
- Three replicates triple the eval's LLM spend.

**Gained:** repeats can never be counted as independent, because they move with their
instance. The interval is reproducible exactly, and no dependency is added.

**New obligations:** a report that quotes an episode-level arm difference quotes the
cluster-bootstrap interval with its instance count, not a row-level Wilson interval.
The replicate count is stated with it.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Repeat each episode back-to-back within one run | In the online mode the second repeat replays the first one's program, so it is not a repeat. |
| statsmodels binomial mixed model | Heavy dependency for one number, and unstable at 47 instances (owner's choice). |
| Row-level Wilson interval over all replicates | Treats repeats as independent, which is the pseudo-replication #6 was filed about. |
| Average each instance first, then take a Wilson interval | Loses the per-fire denominator, which varies by instance, and needs its own weighting rule; resampling instances keeps the pooled definition intact. |

## What would reverse this decision

- An owner decision that the variance components themselves matter, for example to
  say whether instances or run-to-run noise dominate. That needs a model that
  estimates them, and a new ADR accepting the dependency.
- A pair-level (§7 item 1) analysis that needs the same clustering. It would reuse
  this bootstrap, which is an extension, not a reversal.
