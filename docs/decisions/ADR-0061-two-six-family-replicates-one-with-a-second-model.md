# ADR-0061 — Build two six-family replicates, one with a second model, and report them beside runs 11–13

- **Status:** proposed
- **Date:** 2026-11-15
- **Supersedes:** nothing. It carries out issue #266's steps 2 and 3, which ADR-0041 left for
  when a provider key was available.
- **Deciders:** repository owner (issue #266; the key and the spend approved on 2026-11-15).

## Context

The primary result rests on three replicate builds, `results/replicates-2026-10-05/` runs 11–13.
Two things tie it narrowly:
- **One domain.** All three were built before ADR-0041 added `config_renamed`, so they hold
  five git families. The sixth family, whose state is files rather than history, has never been
  built by a model.
- **One compiler.** All three were compiled by `deepseek-flash`. Whether the gate admits
  correct programs, and whether arm 3 then rarely mis-fires, may depend on how this model
  writes probes.

Issue #266 asks for one build per new family and one replicate with a second model. Since
ADR-0041, a plan built from main covers all six families, so one standard build is step 2. The
provider documents two models, `deepseek-flash` and `deepseek-v4-pro` (`provider.py`), so the
second compiler is `deepseek-v4-pro`.

Study 2 (`docs/preregistration/refusal-population.md`) measures build-to-build spread over 20
builds of one model. Two more builds cannot measure a model effect against that spread. So this
decision fixes what is built and what is reported, and registers no hypothesis.

## Decision

1. **Two builds, each `bench.live --primary-only` with the default plan, on main as it stands
   at the build (at or after this record):**
   - **`run-14`:** `deepseek-flash`, the six-family replicate (#266 step 2);
   - **`run-15`:** `deepseek-v4-pro`, the second-model replicate (#266 step 3).

   Both use temperature 0, and record the code commit and the plan in `plan.json` as every run
   does. Neither uses `--build-order` or a refusal set: they are ordinary replicates, not
   study 2 builds.
2. **They are reported beside runs 11–13, descriptively,** in
   `results/replicates-2026-11-15/`, laid out like `results/replicates-2026-10-05/`. The report
   gives, for each run:
   - **the floor and the matched Figure 1 point,** for arm 3 and the lexical arm 2;
   - **per family,** the admitted programs, and arm 3's wrong and total fires;
   - **the config family's rows separately.** It is the domain question, and runs 11–13 have
     no figure for it to be compared with.

   A sentence that compares the two models says it rests on one build each.
3. **What would change the README's primary result:**
   - **`run-15`'s arm 3 mis-fires at a rate comparable to text similarity's.** The method would
     then depend on the compiler, and the primary result would need that qualification.
   - **The config family's programs are admitted and fire wrongly.** The result would then not
     carry outside git history.

   Either is stated plainly if it happens.
4. **Budget:** USD 100 for the two builds together. `deepseek-v4-pro` is about four times
   `deepseek-flash`'s price, and a `deepseek-flash` build costs about one dollar, so the cap is
   generous. A build that the provider stops is resumed with `--resume`, as runs 11–13 were.

## Consequences

**Accepted:**
- **Neither question is tested.** One build per model cannot separate a model effect from the
  build-to-build spread study 2 is measuring. The report says so.
- **The six-family runs are not like-for-like with runs 11–13.** Their pairs include the config
  family. The per-family rows are what compares across the five shared families.
- **One second model, from the same provider.** A model from another provider would separate
  more, and needs a key the owner has not supplied.

**Gained:** the first model-written programs for a non-git family, and the first library
compiled by a second model, both committed and recomputable with no key.

**New obligations:** the report states each build's commit, model and spend; the README's
primary-result paragraph says whether the six-family and second-model runs agree with runs
11–13, and that each rests on one build.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Register a hypothesis on the second model | One build per model has no power against a spread study 2 found to be large (22%–82% fire rates on inexpressible conflicts); a test would decide nothing. |
| Build the config family alone (a one-family plan) | The live plan's breadth cap and admission read every family's negatives; a one-family build would admit under a different gate from every other run. |
| Wait for study 2 and use its configuration-0 builds as #266's step 2 | They permute the plan and serve study 2's own question; #266 asks for an ordinary replicate. |
| A second model from another provider | No key for one; `provider.py` documents only DeepSeek's two models. |

## What would reverse this

A second-provider key, or study 2 finding build spread small enough that two builds per model
could be compared, would justify a registered comparison in place of this descriptive one.
