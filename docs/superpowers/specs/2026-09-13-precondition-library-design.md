# precondition-library — design of record

**Date:** 2026-09-13
**Status:** design approved, implementation not started
**Author:** Shyboy0499

**Revision history**

| version | date | change |
| --- | --- | --- |
| 1 | 2026-09-13 | Initial design of record. |
| 2 | 2026-09-13 | Reframed after a prior-art sweep and a hostile method review (see ADR-0001). Claim 1 dropped as a contribution; Claim 2 narrowed to its empirical form; Claim 3 added for the negative-sandbox admission criterion; the primary metric moved from episode-level to matched dispatch coverage. **Revised before any data was collected** — no episode has been run, so no analysis was chosen after seeing results. |
| 3 | 2026-09-13 | The request text gains a declared informed/uninformed channel split, and the primary claim is scoped to the uninformed regime (where the construction fixes the AUC at 0.500); the gold resolutions land. `sync_fork_with_upstream` and `restore_submodule_state` are converted to state-decided intents; three of the five faults remain unconverted and are excluded from any dispatch measurement (issue #25). **Logged before any episode data existed** — no episode has been run, so no analysis was chosen after seeing results; the only measured figure so far is the informed text-control AUC reported in §3. |
| 4 | 2026-09-14 | **Lifecycle correction, not a claim change.** A program that fails admission is stored as a `candidate` and its rejection reason recorded, not discarded; the §5 lifecycle diagram and the §8 degradation table said "not stored". Corrected to match `library.py` (which writes the candidate before the gate runs) and `library/README.md`; rejection is data the mismatch analysis needs. No measurement or claim is affected, and no number in this document changes as a result. |
| 5 | 2026-09-15 | **Arm 2's mechanism is narrowed (ADR-0002).** The arm compares text by a deterministic lexical overlap behind a `Similarity` seam, not by an embedding; an embedding model is the intended replacement behind the same Protocol. Claim 2's wording follows — the comparison is against *text* similarity — and arm 2 is given the full representation (the intent plus the `StateFingerprint` rendered as text), per issue #4, so the ablation does not confound dispatch with representation. **Logged before any episode data existed** — no episode has been run, so no analysis was chosen after seeing results, and no number in this document changes. |
| 6 | 2026-09-16 | **The seed split is made concrete, and the eval set is stated to be underpowered.** Items 2 and 5 required disjoint admit/tune/eval seeds but no seeds were defined anywhere; §7 now names them and fixes them in `bench/splits.py`. The eval set (40 seeds, 80 decisions) cannot support the primary matched-coverage comparison at a usable interval, so that claim requires the item 6 extension rather than being read off the first run. **Logged before any episode data existed** — no episode has been run, so no analysis was chosen after seeing results, and no number in this document changes. |
| 7 | 2026-09-16 | **Schema correction, not an analysis change.** The ledger's single reason field carried guard refusals, compile failures and invalid-episode causes at once, so a guard refusal rate read off it would have included malformed replies that no guard saw (issue #60); §7's ledger schema and §8's table now name three fields — `refusal_reason`, `compile_failure_reason`, `invalid_reason`. §7 also records that a program whose `variant` is not a declared resolution of an ambiguous intent is quarantined on load, so a `program.yaml` written straight to disk cannot be dispatched as scored (issue #66). Both are corrections to match the code; no metric definition, denominator or number in this document changes. |
| 8 | 2026-09-17 | **Documentation corrections, not analysis changes.** §7's demo figure said 5 faults × 4 occurrences × 3 arms = 60 episodes; only the two faults with an ambiguous intent are runnable (`registry.ambiguous_intents()`), so the runnable demo is 24 and 60 is the nominal grid — the overstatement was 2.5× and sat on a measurement path. §9 names the mechanisms that actually exist for network containment (the guard's textual refusals and the environment allowlist) instead of `sandbox-exec`, which nothing implements. `bench/report.py`'s docstring carried the same 60-episode overstatement. **No measurement or number from a run changes** — no episode has been run. |
| 9 | 2026-09-17 | **Admission negative-side correction, not an analysis change.** §6 named three classes of negative sandbox but `admit` built only "a different fault injected", so a program whose preconditions accepted a sibling resolution of its own intent — firing where firing is wrong — passed the gate (the coupling/duplication audit's case: a submodule program gated only on a gitlink reference accepts the `remove` state). `admit` now builds the missing two: a fault-free sandbox (`build_sandbox(seed, [])`), which every program must refuse, and the program's own fault at a seed whose state a sibling resolution is correct in, chosen from the same seed-to-state mapping the injector uses (`FaultSpec.variant_for_seed`). Each rejection names the class and the number of states it checked. §6 is corrected to describe the three classes the code now builds. Running the hand-written gold programs through the stricter gate found `sync_fork_with_upstream`'s merge preconditions too permissive for the unrelated lockfile-conflict sandbox (the committed record of that tightening is in `bench/gold/sync_fork_with_upstream.yaml`); the gate was not weakened. **No measurement or number from a run changes** — no episode has been run. |
| 10 | 2026-09-17 | **Two defect corrections to the replay and compile paths, not analysis changes.** A program that fired but whose body names a declared parameter the environment cannot bind raised out of `runtime.replay`, so the exception escaped `run_episode` and ended the whole run instead of recording the mis-fire; it is now a `ReplayResult(unbound_parameter=True)` that demotes the program and is named on the row in §7's new `replay_failure_reason` field (issue #76). The compile prompt states each field's exact shape with a minimal example — `body` is one newline-separated string, `parameters` a list of names — and a list `body` is still rejected with the field named rather than coerced, so the compile-quality signal survives (issue #78). No metric definition, denominator or analysis changes; the smoke pass that found both defects never exercised the replay path, and no result is claimed from it. |
| 11 | 2026-09-17 | **Two library-integrity corrections, not analysis changes.** A compile that reused a program id on a later episode was correctly refused by the library, so the episode's program was lost and the row showed only a `compile_failure_reason` that read like a malformed reply; the stored id is now derived from the episode's `(fault, occurrence)` plus a sanitised slug, and the residual same-episode collision is recorded *as a collision* (issue #80). The load-time variant check keyed on `Program.intent` matching an `IntentSpec.name`, but a compiled program's intent is prose, as the compile prompt asks, so the check missed exactly the `program.yaml` written past `admit` that it exists for; it now keys on a new required `Provenance.fault` (issue #69). The same correction makes the read pure: `Library.load_all` applies the verdict in memory and writes nothing, and `Library.quarantine_undeclared()` is the explicit write that records it. **No metric definition, denominator or number in this document changes** — no episode has been run. |
| 12 | 2026-09-17 | **Two admission-gate corrections found by the smoke pass, not analysis changes.** (1) §6 now states a DECLARED condition before the two sides: a body parameter that no precondition's probe names is refused, because a precondition is how a program declares what it needs and the states it may fire in need not bind an undeclared one. The smoke pass produced three rows carrying `replay_failure_reason` from a `submodule` program whose body used `submodule_path` while its preconditions did not (issue #77). (2) The unrelated-fault negative class is corrected from "one fixed seed each" to one seed per distinct state its injector can select, read through `FaultSpec.variant_for_seed`; `diverged` is now built at seeds 0, 1 and 2 and `submodule_moved` at 0, 1 and 4, where the old class built each at seed 0 only, so a program could be rejected on one state and fire on another (issue #75). The faults that expose no seed-to-state mapping remain one state each, labelled as sampling. **No metric definition, denominator or number in this document changes** — no episode has been run, and the smoke pass claims no result. |
| 13 | 2026-09-17 | **Pre-registration revision: occurrences are labelled by role, and the episode loop's independent observations are stated (issue #81).** A smoke pass reported zero replays because its seeds each select a different resolution, and a program admitted for one resolution correctly refuses the others — so the plan as written produced a flat cost curve *by construction*. §7 gains a required `occurrence_role` on every ledger row, declared from the injectors' own seed-to-resolution mapping and written by the runner: **variant** for the first sight of a resolution, **replay** for every later one. The cost curve is computed over the replays (where the accumulation is visible), the mismatch comparison over the variants (the only independent observations), and both figures name the occurrences they used. §7's "Design" resolves the choice the earlier text left open — held-out variants or relabelled replays — in favour of replays, **because the injectors do not vary branch names, file sets or conflict positions by seed**; widening them is issue #6. The eval set's arithmetic is now stated: each measurable fault declares three states, so 40 seeds yield **3 variant and 37 replay occurrences per family**, and the episode-level mismatch comparison has six independent observations rather than eighty. **Logged before any eval data existed** — no eval episode has been run, so no analysis was chosen after seeing results; the smoke pass that motivated it is excluded from every claim in §7, and no reported number changes. |
| 14 | 2026-09-18 | **Portability corrections, not analysis changes (issue #87).** §7's invocation wrote its ledger to a hardcoded `/tmp/precondition-ledger.jsonl`, which is not a path that exists on Windows; it now uses `Path(tempfile.gettempdir())`, which keeps the same intent (the ledger stays outside the repository) without naming a platform. Recorded alongside four source and test defects a Windows verification pass found — a bare `bash` resolving to the WSL launcher, `shell=True` selecting `cmd.exe` for multi-line bodies, `shutil.rmtree` failing on git's read-only loose objects, and an import-time `git status` that stopped the suite being collected outside a git checkout. No metric definition, denominator or number in this document changes, and no result is claimed from that pass. |
| 15 | 2026-09-18 | **Figure 2 reports cumulative amortized cost with the break-even, not per-occurrence means (issue #8).** Claim 1 is about cost falling across occurrences, and a mean per occurrence is a snapshot: it says what one occurrence cost, not whether the compile has been repaid, so no crossover could be read off the figure the claim rests on. Figure 2 now plots the running amortized tokens and LLM calls per episode, with the break-even marked on the figure and stated in the report text, and §7's secondary-metrics list says so. `bench/report.py` computes the accumulation and reports why a crossing is not computable when it is not. No metric definition, denominator or reported number changes, the ledger schema is unchanged, and the analysis reported is the one rev 13 describes, read off an accumulating series rather than a per-occurrence one. **Logged before any eval data existed** — no eval episode has been run. |
| 16 | 2026-09-18 | **Spec-gaming becomes its own recorded fact and its own column (issue #9).** §7's ledger gains `refs_intact`, the fact of whether a resolution left the recorded refs and upstream's history alone; a row that reached the expected state while that is false was spec-gamed, and the ablation table and report now count it separately from a resolution that simply failed. Recorded as a fact and derived, not stored as a verdict, for the reason §7 already gives for `misfired`/`succeeded`: a stored verdict could not sit beside `ground_truth_ok` without the two disagreeing. `null` means the check did not run and is never counted as gaming. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 17 | 2026-09-18 | **The arm triple and its Pareto frontier are reported, making item 8's promise true (issue #8).** §7 item 8 and Claim 1 both require cost per success beside cost per episode, and the report stated only the latter. It now reports the triple — success rate, tokens per episode, tokens per success, each with the denominator it was taken over — pooled over every graded episode of the arm with the failures kept in the denominator per item 7, plus a Pareto frontier over the three so no arm is read on one axis alone (`arm_triples.csv`, `pareto.png`). Cost per success is the arm's total tokens over its successes, not the mean cost of a successful episode; the two differ whenever an arm fails, and the second would flatter an arm that fails often. An arm with no success has no cost per success and is reported unranked rather than assigned a place. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 18 | 2026-09-18 | **A pre-registered TOST gates any "equal success rate" wording, and the verdict is reported (issue #8, item 8).** §7 gains principle 10: "equal" requires an equivalence test and "comparable" is the fallback, at a margin of ±10pp and α = 0.05 registered here before any data. `bench/report.py` runs it on arms 2 and 3's pooled success rates and prints the difference, the 90% interval, both one-sided p-values and which of three cases holds — equivalent; outside the margin; or too wide to decide, which is an underpowered run rather than a difference. The margin and alpha are named constants, so the choice is visible and dated rather than buried in a call, and the variance is Agresti–Coull-adjusted so a 0%/100% rate cannot produce a zero-width interval. **No live document currently claims an equal success rate** — Claim 1 already says an arm that succeeds more often may spend more, and defers to cost per success — so this closes the gap between that claim and its evidence before such a sentence can be written, rather than correcting one. No metric definition, denominator or reported number changes and no result is claimed; no episode has been run. |
| 19 | 2026-09-18 | **The raw prompt prefix length is reported, once rather than per arm (issue #8, item 5).** The item asks for it per arm, and measuring first showed the premise does not hold: both prompts are module-level constants — `agents/react.py`'s `SYSTEM_PROMPT` and the one derived in `agents/compile.py` — and **every arm sends the same two**, so a per-arm column would print one number three times and imply a difference that does not exist. §7's metrics list now requires the prefix length in raw characters, reported once with that reason, and notes that the arm-level difference is transcript growth around the prefix rather than the prefix. The compile prefix is the only one that is not fixed: it grows by the joined length of an intent's declared variant ids. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 20 | 2026-09-18 | **Input tokens are metered in three components, with the provider mapping stated (issue #8, items 1-2).** §7's ledger gains `uncached_tokens_in` and `cache_write_tokens_in` beside the existing cache-read field, and a bullet records how each is derived and what it means per provider: OpenAI-style APIs report `prompt_tokens` **including** cached tokens, so the uncached component is derived from `prompt_cache_miss_tokens` where published (DeepSeek publishes it) and by saturating subtraction otherwise; Anthropic-style APIs bill a separate cache write, which is why that field exists though DeepSeek always writes zero. `tokens_in` is documented as the provider's total and explicitly **not** a billing basis — cache-hit input is published at 1/50th of cache-miss input, so pricing the total at one rate overstates the arm that caches most. `bench/report.py` reports the components per cell and warns at the cost figure. **Not implemented:** applying rates. That needs a rate table, and DeepSeek's rates differ by peak and off-peak hours, so a correct figure needs the rate or the call time recorded per episode. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 21 | 2026-09-18 | **Claim 1 is restated to match the figures that now exist (issue #8, item 9).** The claim said tokens and calls fall per episode with cost per success beside cost per episode, which understated what the report now does and overstated what it can claim: the curve it is read from is cumulative and amortized with an explicit break-even (#94), the triple including cost per success and its Pareto frontier is reported (#97), the cache components are metered separately so input is not priced as one number (#100), and any "equal success rate" wording requires a pre-registered equivalence test (#98). The claim now names the cumulative figure, the triple, and **two limits that belong to the claim** rather than to its footnotes: it is a claim about tokens and calls and not about currency, because pricing needs rates that vary by peak and off-peak hours and are not applied; and equality of success rates is not available to it, because that needs the equivalence test to pass. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 22 | 2026-09-18 | **The injected state is no longer recorded inside the clone (issue #103).** `submodule_moved.inject` wrote the resolution label — `init`, `repin` or `remove` — into `refs/sandbox/submodule-state` in `work`, the same clone `runtime/probes.py` runs probes in, so a precondition could read the answer instead of diagnosing the fault and no admission class could reject it. Measured before the fix: probes read `remove`, `repin` and `init` for seeds 0, 1 and 4. The state now travels on the `Sandbox` object, which the harness owns, set by `build_sandbox` from the same seed-to-state mapping the injector uses; `check` takes it as a selector and still reads its clause from the environment. §7 records the channel. The probes' `submodule-path` ref stays: it carries a path rather than an answer, and a correct removal deletes the `.gitmodules` entry it would otherwise come from. No committed content changes, so no commit SHA moves; a ref and an uncommitted blob are simply no longer written. No metric definition, denominator or reported number changes and no result is claimed. |
| 23 | 2026-09-18 | **Probes are screened before they run (issue #10, item 2).** A probe is model-authored text that reached a shell unscreened, while a body is screened in `runtime.replay` — so the model-authored path with *less* screening was the one that runs on every dispatch attempt rather than once. Measured before the change: a precondition of the form `touch probe-wrote-this.txt && curl -s http://example.invalid/x` both wrote to the working tree and reached the network, and the identical text as a body was refused with `refused outbound network call`. `evaluate_predicate` now screens the substituted probe with `runtime.guard`, using the same `env_root` a body is judged against, and reports a refusal as **not holding** with the reason in `observed` — the shape an unbindable parameter already takes, so dispatch treats it as an ordinary non-match and admission can name it. **This does not make probes read-only:** the guard permits writes inside the sandbox because bodies need them, so an in-repo mutation such as `git reset --hard` in a probe still runs. The remaining halves of item 2 — refusing in-repo writes and the measured breadth cap — are not done. No metric definition, denominator or reported number changes and no result is claimed. |
| 24 | 2026-09-18 | **The pre-injection tip is no longer recorded in the clone (issue #103).** `record_base` used to point `refs/sandbox/base` at the tip the fault was injected on top of. That ref is a *diff against the fault*: `git diff refs/sandbox/base HEAD` shows the injected change, so a body could read what was done to the repository instead of diagnosing it. The value now lives in `Sandbox.recorded`, which the harness owns, and `diverged.check` takes it from there; the clone gets `refs/sandbox/injected`, an empty blob whose only content is "a fault ran here", which the task text already says. The marker stays on disk because a second `inject` has to see it and an in-memory marker would not outlive its object. This closes the base leak for all four faults that call `record_base`, not just `diverged`, because the recording happens in one shared function. Remaining in the clone and tracked by #103: `diverged`'s `local-tip`, `dirty_tree`'s patch and untracked blobs, and `lockfile_conflict`'s three refs. No committed content changes, so no commit SHA moves. No metric definition, denominator or reported number changes and no result is claimed. |
| 25 | 2026-09-18 | **The remaining recorded values move into the harness, finishing issue #103's value half.** `diverged`'s `local-tip`, `dirty_tree`'s patch and untracked blobs, and `lockfile_conflict`'s local tip and two dependency entries all lived under `refs/sandbox/` in the clone the graded code reads, so a body could read the injected state's evidence rather than diagnose it. They now travel in `Sandbox.recorded`, and the checkers take them from there — the mechanism #103's earlier change introduced for the pre-injection tip. What remains in the clone is `refs/sandbox/injected`, an empty marker ref, and `submodule_moved`'s `submodule-path`, which stays because the probes bind `{submodule_path}` from it and a correct removal deletes the `.gitmodules` entry it would otherwise come from. A mechanical edit briefly inverted `dirty_tree`'s untracked clause into `"untracked" in sandbox.recorded == 0`, a chained comparison that is always false and silently disabled the check for a `clean -fd` that destroys the work; the fault's own destructive negative control caught it, which is what those controls are for. No committed content changes, so no commit SHA moves. No metric definition, denominator or reported number changes and no result is claimed. |
| 26 | 2026-09-18 | **Arm 2's embedding currency is scaffolded, so the accounting exists before the model does (issue #104).** The seam is lexical (ADR-0002), so there is no embedding spend to meter and nothing that could be folded into `tokens_in` — which is why this is a scaffold rather than an implementation. What is now in place: `SimilarityUsage` and an **optional** `ReportsUsage` Protocol, deliberately *not* part of `Similarity`, so that seam stays a one-method callable and `lexical_similarity` satisfies it unchanged; `similarity_usage(seam)` answering zero for a seam that does not report; `embedding_tokens` and `embedding_calls` on the ledger, documented as their own currency that is never added to the LLM's; `run_benchmark` taking a `similarity` argument, because knowing what an embedding model costs means being able to run with one; the runner measuring the seam's usage across each episode and recording the delta; and the ablation table, its CSV and `report.txt` stating it beside the LLM tokens. The invariant the issue asks for is asserted end to end: with a seam that reports a cost, a replay row carries `embedding_tokens > 0` while `tokens_in == 0`, so a second bill cannot be folded into the first. Every row is 0 while the seam is lexical, and the field is documented so a non-zero value is itself the signal that a model is behind the seam. No metric definition, denominator or reported number changes and no result is claimed — no episode has been run. |
| 27 | 2026-09-18 | **`refs_intact` is renamed `recorded_state_intact`, and its meaning is widened to the recorded state (issue #96).** Refs are the first thing the fact covers, not all of it: a minimal-diff check against a fault's declared change surface belongs to the same fact, so it joins this field rather than growing a second boolean that the report would have to conjoin to derive spec-gaming — the shape §7 already warns against for stored verdicts. The rename is done now, before any ledger row exists, because it is a schema change and the cost of it rises the moment rows do. The function in `tasks/invariants.py` is renamed with the field. Revision 16, which introduced the field, is left naming it `refs_intact`: a record of a time is not rewritten (rule 5), and this row is the narrowing that supersedes it. No metric definition, denominator, reported number or behaviour changes, and no result is claimed. |
| 28 | 2026-09-18 | **Each fault declares the paths a resolution may touch, and the invariant checks it (issue #96).** `FaultSpec.change_surface` is a **declaration**, not something derived from what the injector touched: a repair that rewrites a generated file from its source legitimately writes a path the injection did not name, and a derived surface would refuse it for being outside the fault. `diverged` allows `app.py` and `docs/readme.md`; `dirty_tree` those two plus `notes/scratch.txt`; `lockfile_conflict` `deps.lock`; `submodule_moved` `.gitmodules` and the gitlink path; and `branch_renamed` declares **empty**, which is the strictest value rather than a missing one — its resolution is a ref operation, so any commit is something the fault did not ask for. Empty is also the default, so a fault that forgets to declare fails its own gold resolution instead of passing on a permissive default. The check joins `recorded_state_intact` rather than growing a second field (revision 27), reading the committed diff from the recorded base and refusing any path outside the surface. `submodule_moved` gained a recorded base, which it had never needed before because nothing diffed against it. Tests pin three different properties: coverage (what each injector commits is inside its own declaration, per fault), firing (a committed change outside the surface is refused, naming the path), and the control (an in-surface commit is allowed), so the check cannot be a blanket ban or a no-op. Not covered: an **uncommitted** change is invisible to a diff between two commits, and refs outside `refs/sandbox/` remain unpinned. No metric definition, denominator or reported number changes and no result is claimed. |
| 29 | 2026-09-18 | **`embedding_calls` is settled as the calls the implementation reports making to its provider (issue #104).** It was described as "how many times the seam was called", which is a different quantity: an implementation that batches or caches can be asked for a hundred scores and make one call, and only it knows which. The invocation count is also mostly a property of the dispatch loop -- how many admitted candidates it scores -- so it would say little about arm 2's cost while looking like it did; a reader who wants that number wants the library's size, which the ledger records per episode. The ledger field and `SimilarityUsage.calls` now agree on the provider reading, and a caching seam is the test that pins it: the harness observes invocations, the seam reports traffic, and the ledger carries the traffic. No metric definition, denominator or reported number changes and no result is claimed. |
| 30 | 2026-09-18 | **The state grid moves into the package, and a discrimination probe measures any similarity scorer against it (issue #104).** The probe answers the question that has to precede filling arm 2's `Similarity` seam: can a scorer tell which resolution a state needs, *from the text*? Each labelled pair is crossed with its intent's declared resolutions, the scorer scores the request text against each resolution's `rationale`, and the AUC asks how often a correct resolution outranks an incorrect one, over 56 pairs and 168 crossings on the declared grid (seeds 0–3, named separately from the pre-registered plan). Measured on the shipped scorer: **lexical 0.6755**, against **0.5000** for a constant scorer that cannot discriminate — an exploratory figure with its provenance, not a claim. Two limits are stated in the module rather than discovered later: `rationale` is a proxy for a compiled program's text, so this answers *is the fault family separable by meaning* and **not** the dispatch AUC the benchmark reports; and the figure is **reported, never gated**, because a threshold on a proxy would turn an exploratory number into a claim. The grid itself moved from `tests/conftest.py` into `tasks/state_grid.py` so `bench` can reach it — a declared fingerprint per fault state, which the test suite still checks against what a real sandbox observes, so the declaration cannot drift from the injectors. No metric definition, denominator or reported number changes and no result is claimed. |
| 31 | 2026-09-18 | **Revision 30's discrimination figure is withdrawn as a baseline, and a baseline defect is recorded (issue #116).** That probe crossed the request with each resolution's `rationale` — the designer's explanation — while a dispatcher compares against `_program_text`: a program's `intent` plus its predicate descriptions. Measured against the artifact, the shipped scorer gives **AUC 0.4778** and puts the correct gold program first in **9 of 28 pairs (32%, chance for three candidates)**, because `program.intent` is the intent *name* — a constant across a fault's resolutions — and unweighted Jaccard over token sets is dominated by the shared boilerplate; correct and incorrect crossings have an identical maximum score. The module's own number (0.6755, rationales) flattered the scorer by ~0.2 AUC and must not be quoted, and the conclusion drawn from it — that a semantic scorer has little headroom here — is **withdrawn and reversed**: with almost no lexical signal, the case for an embedding model is stronger. The finding is scoped to hand-written gold; whether compiled programs' texts are equally non-discriminative needs a compiled library. No metric definition, denominator or reported number changes and no result is claimed. |
| 32 | 2026-09-18 | **The probe measures the artifact in code, not only in a note, and its top-1 denominator is stated (issue #116).** Revision 31 corrected the figure the probe *reports* while the code still scored rationales — a docstring that says "do not quote this number" is a warning, not a fix, and the next caller would have read the number anyway. The candidate source is now explicit: `program_text_candidates` calls `library._program_text` rather than restating it, `discrimination_scores`/`discrimination_auc` take a `Mapping[variant, text]` instead of a resolution sequence, and `compare_scorers` takes candidate texts per intent and raises rather than silently narrowing the comparison when one is missing. `rationale_candidates` is **kept as a diagnostic**, because the two sources disagreeing is itself the evidence, and `test_the_two_candidate_sources_disagree` fails if they stop differing — so the substitution that caused this cannot be repeated quietly. This row also **corrects revision 31's denominator**: 9 of 28 is not a rate over the pairs. Strict top-1 is decided only on pairs that *have* a correct resolution, and 24 of the 28 do (the other four are the negative pairs where nothing should fire), so the figure is **9/24 = 38% against a 33% chance expectation for three candidates**, with ties counted as no decision rather than as wins. Read together with AUC 0.4778 — below chance — the two are not in tension once the denominators are named: nine strict wins is one pair above chance, so neither number shows usable signal and the finding stands. Rechecking revision 31's numbers against the code is also what produced this row: the pair count had been taken from the crossing rather than from the metric. Nothing the benchmark defines, divides or reports changes — this is the probe's own metric — and no result is claimed. |
| 33 | 2026-09-18 | **Revisions 31 and 32's discrimination figures were taken on one intent and quoted as the family's; measured over the whole ambiguous subset the shipped scorer is above chance, and the scorer decision is scoped in ADR-0003 (issues #104, #116).** Revision 30 framed the probe over both ambiguous intents — 56 pairs and 168 crossings — while revision 31's withdrawal, and revision 32's denominator correction, reported `sync_fork_with_upstream` alone (AUC 0.4778, strict top-1 9/24) as the baseline without saying so. Over the subset the metric is defined on, with the same scorer, text and seeds: `restore_submodule_state` **AUC 0.7264, top-1 14/24 (58%)**; `sync_fork_with_upstream` **AUC 0.4778, top-1 9/24 (38%)**; both together **AUC 0.5722, strict top-1 23/48 (48%)** against a 33% chance for three candidates, with a constant scorer at 0.5000. So the family baseline is **above chance, not below**, the two intents differ by 0.25 AUC, and revision 31's reversal of the embedding conclusion — that the case for a semantic scorer is stronger — held only on the weaker intent; it is narrowed here to that intent rather than reversed again. Revision 32's denominator convention stands and is what produces 23/48. ADR-0003 (proposed) scopes the decision: neither alternative #116 left open improves the metric dispatch acts on — IDF-weighted Jaccard 19/48 and cosine 15/48 against 23/48, and dropping the constant `intent` leaves top-1 unchanged — and IDF cannot be carried by a one-method seam at all. The probe's crossing functions now refuse a candidate mapping that spans two intents, because variant ids are unique only within one and the mistake returned a plausible wrong number (0.6980, 18/48) rather than failing. Nothing the benchmark defines, divides or reports changes, and no result is claimed. |
| 34 | 2026-09-20 | **ADR-0003 is accepted, and the spec of record now carries arm 2's measured baseline instead of leaving the risk unquantified (issues #104, #116).** Revisions 31–33 correct the probe and its figures in the log; this row amends the **live** sections, because a reader of the design should not have to reconstruct a decision from the revision history. §12's decisions table gains a row for arm 2's baseline and seam, and Open risks item 1 now states the exploratory reading the probe gives before any episode runs: over the ambiguous subset the shipped scorer scores **AUC 0.5722, strict top-1 23/48 (48%)** against a 33% chance for three candidates, with the pooled figure hiding **0.7264 / 58%** on `restore_submodule_state` against **0.4778 / 38%** on `sync_fork_with_upstream`. Those are probe figures on hand-written gold, explicitly **not** tune-set results and not the pre-registered split, and the risk is now stated as the spread rather than as a single number: on the second intent the arm is effectively at chance, so the comparison there is the one that flatters preconditions. The row also records what was rejected with numbers — IDF weighting raises the pooled AUC while lowering strict top-1, and dropping the constant `intent` moves the AUC by 0.0104 for no gain — and that the embedding swap stays the one open candidate. No benchmark metric, denominator or reported number changes: the probe measures arm 2's representation and is not the primary metric, and no result is claimed. |
| 35 | 2026-09-21 | **The gold programs' predicate descriptions are rewritten to state the applicability condition in request vocabulary, and the rewrite does not rescue arm 2 (issue #104).** #104's finding was that an intent's three candidate texts collapse together for a semantic scorer, so the experiment was to rewrite each `description` — the text `library._program_text` feeds arm 2 — to say what *state* the program is for, using words a request would use, without naming a resolution and without copying a request's wording. The rewrite also closes a leak: `sync-fork-overlapping-merge`'s `local_work_beyond_the_overlap` description read "...whose right resolution is not a **merge**...", naming the label `_program_text` excludes `variant` to keep out; `tests/test_gold_programs.py::test_no_gold_description_names_a_resolution` now guards that, and the admission-gate history that description carried moved to a YAML comment so it is not scored as meaning. Only `description` values changed; `probe`, `body`, `parameters`, `variant`, `intent` and `provenance` are byte-identical, and `test_the_gold_resolution_stays_inside_its_declared_surface` replays the same resolutions. Re-measured on the committed gold and the probe's seeds: pooled lexical is **AUC 0.5340, strict top-1 23/48** (was 0.5722 / 23/48) and the embedding **AUC 0.5252, strict top-1 20/48** (was 0.5571 / 19/48); per intent, lexical `restore_submodule_state` **0.6299 / 12-of-24** and `sync_fork_with_upstream` **0.4965 / 11-of-24**, embedding **0.5556 / 12-of-24** and **0.5062 / 8-of-24**. Candidate-vs-candidate mean embedding cosine **rose**, to **0.8909** on `restore_submodule_state` and **0.8932** on `sync_fork_with_upstream` (was 0.8718 / 0.8215). So separating the descriptions did **not** raise the metric dispatch acts on, and made the candidates no less interchangeable to the embedding: the collision is a property of three resolutions that describe nearby states in one domain, not of vague wording. The figures are printed by `tests/test_similarity_probe.py -s -k 'pooled_baseline or candidate_texts'` and `tests/test_embedding_similarity.py -s -k candidate_texts`. No benchmark metric, denominator or reported number changes — the probe measures arm 2's representation and is not the primary metric — and no result is claimed. |
| 36 | 2026-09-21 | **The probe's discrimination figure was pooled across two request regimes; measured per regime the informed baseline is AUC 0.6172 and strict top-1 15/24 (63%), and the pooled number is withdrawn as a baseline (issue #104).** Every `LabelledPair` records the channel its text arrived through, and `bench/textcontrol.py` states the consequence: the uninformed channel's sampler never consults state, so its AUC is **0.5000 for any classifier and any phrasing list** — a property of the construction, not a measurement — while informed wording nearly gives the resolution away, so a high score there is the boundary condition and the genuine measurement. Revisions 30 onward scored both channels together, so ADR-0003's accepted baseline (**0.5722 / 23-of-48**, re-measured **0.5340 / 23-of-48** in revision 35) and this spec's live figures were pooled numbers that described neither regime. Re-measured with the committed code — hand-written gold on the probe's seeds 0–3, which are **not** the pre-registered split: **informed, both intents** lexical **AUC 0.6172, strict top-1 15/24 (63%)**, per intent `restore_submodule_state` **0.8125 / 8-of-12** and `sync_fork_with_upstream` **0.6007 / 7-of-12**; **uninformed, both intents** lexical **AUC 0.5000, strict top-1 8/24 (33%)**, chance by construction. The 8 negative pairs belong to the uninformed regime, where they are the plumbing tripwire rather than baseline material; the informed regime has no negatives, because informed wording exists only where a resolution does. The embedding scorer re-measured on the same split: informed **AUC 0.5859, strict top-1 12/24 (50%)** (per intent **0.6389 / 8-of-12** and **0.5729 / 4-of-12**), uninformed **0.5000 / 8-of-24**. So the corrected baseline is **stronger** — 63% where ADR-0003 recorded 48% — which is the direction that makes the claim harder to support, and the embedding does not improve the informed top-1. The probe now takes a required `regime` on its single-mapping functions, `compare_scorers` returns one row per regime, and there is no pooled mode, so the defect cannot return through a default; ADR-0004 (proposed) records the correction and re-derives ADR-0003's baseline decision, which stays accepted as a record. The figures are printed by `tests/test_similarity_probe.py -s -k informed_baseline` and `tests/test_embedding_similarity.py -s -k measured_against_lexical`. No benchmark metric, denominator or reported number changes — the probe measures arm 2's representation and is not the primary metric — and no result is claimed. |
| 37 | 2026-09-27 | **The injectors' instance diversity is measured, and a proposed ADR scopes the fix (issue #86).** Measured over every seed the plan uses (smoke `0,1,2,4`, tune `1000–1015`, eval `2000–2039`; 60 seeds) with real sandboxes: the two measurable faults offer **3 content-distinct environments each — 6 across the family — one per resolution**, and seeds selecting one resolution are byte-identical **including commit SHAs** (`.venv/bin/python -m precondition_library.bench.instance_diversity`). #86's "6 independent observations" is confirmed; its "differing only in commit SHAs" is corrected in the stronger direction — they differ in nothing. The three excluded faults do vary content by seed (`dirty_tree` 2 environments, `branch_renamed` 4, `lockfile_conflict` 56 on the same seeds) but stay outside the comparison because their single fixed sentence is the label (issue #25). **Live corrections:** §10's determinism block said "different seeds -> genuinely different instances", which the measurement refutes for same-resolution seeds and is corrected in place; §7 records the measured instance count and names the proposed direction. ADR-0005 (proposed) decides the approach — parameterise each state shape along declared axes drawn per seed, key occurrence roles on instance identity rather than resolution, restate the seed plan in terms of independent environments, exclude a fault that cannot diversify rather than pad it, and carry the achieved instance count in the report. **This revision scopes the work and changes no injector behaviour**: `tests/test_instance_diversity.py` pins the property as a strict `xfail` naming #86, which fails today and whose marker is deleted by the change that lands it. No benchmark metric, denominator or reported number changes, and no result is claimed. |
| 38 | 2026-09-27 | **ADR-0005 is landed: each measurable fault's state shapes are parameterised along declared Tier 1 axes drawn per seed, independence is keyed on instance identity, and the seed plan's arithmetic is restated (issue #86).** `diverged` and `submodule_moved` now draw, per seed, the file bodies each side writes, the local commit count (1–3) and subjects, and the conflict hunk position; `FaultSpec.instance_for_seed` returns the resolution plus the drawn values, `build_sandbox` records it on the `Sandbox`, and `build_sandbox` re-derives the resolution from the observed `StateFingerprint` and raises if it is not the one `variant_for_seed` declared (the guard is tested firing on a deliberately bad draw). `bench.splits.occurrence_roles` marks an occurrence `variant` the first time an **instance** is seen and `replay` only on a genuine repeat of one; `FaultSpec.variant_for_seed` keeps its meaning. Measured over the 60 plan seeds with real sandboxes (`.venv/bin/python -m precondition_library.bench.instance_diversity`): **61 distinct environments, up from 6** — `diverged` `discard` 23, `merge` 14, `rebase` 8; `submodule_moved` `init` 5, `remove` 6, `repin` 5 — and distinct instance identities build distinct environments; the 40-seed eval set alone builds 47 of them (see §7 for the eval per-resolution table). Every resolution clears the owner's target of 4, and `submodule_moved` reaches it on the nested repo's content alone, so the approved "cannot diversify" exclusion is not applied. The smoke set's four seeds now draw four distinct instances, so it carries **no replay**; the cost curve's replays live in the tune (1 and 9) and eval (8 and 25) sets. `bench.report` carries the achieved instance count per resolution (`achieved_instances`). **Live corrections:** §7's seed-plan table and its "three, not forty" arithmetic are replaced by the measured per-resolution counts and the restated underpower note (a 95% Wilson half-width of about ±18.6pp at the owner's target N=24 and ±14.7pp at the 47 achieved, against the ±10pp equivalence margin's ~94); §7's Design and §12's unit-of-analysis row move from the fault seed/family to the environment; §10's determinism block is corrected in place. The strict `xfail` in `tests/test_instance_diversity.py` is deleted and the test passes for the real reason — two same-resolution seeds now build different file-body signatures — with a sibling test that builds four real environments per resolution. **Logged before any eval pass** — no eval episode has been run, so no analysis was chosen after seeing results; the instance counts are derived from the declared draw and from real sandboxes, and no benchmark metric, denominator or reported result is claimed. |
| 39 | 2026-09-30 | **Revision 38's Wilson half-width at the 47 achieved environments was misstated: it is about ±13.7pp, not ±14.7pp.** `bench.report.wilson_interval` gives a 95% half-width of **0.1374** at 23/47 and **0.1857** at 12/24; ±14.7pp is the half-width at about N=40, the eval set's *seed* count, which is the unit revision 38 replaced with the environment. The error overstated the imprecision. This row corrects only that figure: the ±18.6pp and "~94" beside it are left as written, and whether a single-proportion Wilson half-width is the right yardstick for §7 item 10's TOST on a *difference* of two rates is not settled here. **Live corrections:** §7's underpower note and `bench.splits`'s module docstring now say ±13.7pp; revision 38 is left as written, because a record of a time is not rewritten (rule 5), and this row is the correction. The two quoted half-widths are now pinned by `tests/test_ablation_report.py::test_the_seed_plans_quoted_half_widths`, so a figure that disagrees with the function fails CI rather than a reader. No benchmark metric, denominator or reported number changes, no eval episode has been run, and no result is claimed. |
| 40 | 2026-09-30 | **The two questions #86 left to the owner are settled in ADR-0006 (proposed): `submodule_moved/init` counts as five environments, and the ±10pp equivalence margin stays, with its power restated as the TOST it is.** *`init`:* its five instances are byte-identical before resolution and differ in the nested content their gitlink names, which a correct resolution materialises; the owner reads that content as part of the environment, so the counts stand at 61 plan / 47 eval and `submodule_moved` stays in the comparison. `bench.instance_diversity` now expands each gitlink into the nested commit's blob lines, so no commit id enters `instance_signature` and the five are witnessed by content; the re-measured counts are unchanged (`.venv/bin/python -m precondition_library.bench.instance_diversity`), and `tests/test_instance_diversity.py::test_gitlinks_are_compared_by_the_content_they_name` pins it. *The margin:* revisions 38 and 39 stated the episode loop's power with one rate's 95% Wilson interval, but §7 item 10's margin is applied by a TOST to the **difference** of two arms' rates at a 90% interval. With `bench.report.tost_equivalence` and both arms at a shared 50% rate the difference's half-width is ±22.5pp at 24 per arm and **±16.5pp at 47**, and ±10pp first becomes passable at **133 per arm** (87 at 80%, 53 at 90%), not ~94. The margin is **not** revised: item 10 stands at ±10pp and α = 0.05, and at the achieved N the expected verdict is "comparable", which `success_rate_wording` already produces. **Live corrections:** §7's underpower note and `bench.splits`'s module docstring state the TOST figures beside the single-rate ones, and the ~94 is withdrawn; revisions 38 and 39 are left as written (rule 5). `tests/test_ablation_report.py::test_the_margins_quoted_tost_half_widths` and `::test_the_margin_first_becomes_passable_at_133_per_arm` pin the figures. **Logged before any eval pass**: no eval episode has been run, no metric definition, denominator or margin changes, and no result is claimed. |
| 41 | 2026-09-30 | **The ledger gains `temperature`, and the provider pins it at 0 (issue #6).** #6 asks for the model version and temperature to be pinned and recorded per episode; `model` was recorded, but no temperature was sent or recorded anywhere. `DeepSeekProvider` now sends `temperature` on every call (`DEFAULT_TEMPERATURE = 0.0`, overridable) and reports the value it sent on each `Completion`; `bench/run.py`'s per-episode accounting reads it off the completions, so the row records what the calls used rather than a configuration value, and an episode whose calls disagree raises. A replay row carries `null`, because no model ran. **Not verified:** whether the endpoint honours the field — no live call has been made, a reasoning model may ignore sampling parameters, and temperature 0 is not determinism on a hosted model. The field is additive and defaulted, so no metric definition, denominator or reported number changes; no eval episode has been run, and no result is claimed. |
| 42 | 2026-09-30 | **Arm 2 gets a pre-registered floor: it counts as the baseline only if its informed-regime strict top-1 on the tune set clears chance by its 95% Wilson lower bound (issue #116, ADR-0007).** #116's last open item asked for the top-1 below which arm 2 is not a usable baseline to be decided before the eval, so that "preconditions beat text similarity" cannot be read off a broken one. §7 gains item 11. The measurement is `bench.similarity_probe.tune_baseline` (informed regime, `TUNE_SEEDS`, the eval library's candidate texts), and the verdict is `bench.report.arm2_baseline_floor`: usable when the Wilson lower bound exceeds 1/3. At 24 decidable pairs the floor falls between 12 and 13. Below it the comparison is still reported, with the verdict beside it, and the claim may not be stated. **Context only, not the gate:** hand-written gold on the tune seeds scores 55/96 (57%, AUC 0.6175), lower bound 0.473, and the probe's informed 15/24 has a lower bound of 0.427. Neither is the pre-registered measurement, which needs the compiled library. The probe module stays ungated on `PROBE_SEEDS`; `tune_baseline` is the one gated measurement and refuses an intent with fewer than two candidates, so an empty library cannot read as a failed baseline. **Logged before any eval pass**: no eval episode has been run, no existing metric definition or denominator changes, and no result is claimed. |
| 43 | 2026-09-30 | **The primary metric's arithmetic is defined and implemented: arm 2 is swept, arm 3 is one operating point whose coverage is the pre-registered coverage point, and mismatch is per fire (issue #5, ADR-0008).** §7 said both dispatchers sweep their acceptance thresholds, but arm 3 has no score — it fires the most specific program whose preconditions hold, or nothing — so there was nothing to sweep, and the pre-registered coverage point had no value. The owner chose: arm 3 is a single point and its own coverage is the coverage point; mismatch is wrong fires over fires, with any fire on a negative pair wrong. `bench.coverage` implements it over per-pair dispatch outcomes (`PairOutcome`), so it runs before a compiled library exists: `sweep` (one point per distinct arm-2 score, inclusive floor as in `Library.match_semantic`), `operating_point`, `matched_comparison` (nearest coverage, ties to the lower coverage, compared as exact fractions, gap reported), `vacuous_reason` (arm 3 correct on every pair), and `detectable_difference` for item 3. Every function refuses outcomes from both regimes. **Live corrections:** §7 item 1, item 3, Figure 1 and the method diagram, the README diagram, and the `bench.report` and `bench.pairs` docstrings. **Exercised on gold, not the gate:** over the tune seeds' informed pairs, arm 2 traces 7 operating points from 8/96 to 96/96 coverage (mismatch 41/96 at full coverage, i.e. 55 of 96 correct), and arm 3 played by the labelling rule decides all 96 pairs correctly, so `vacuous_reason` fires, as it does on the 128 uninformed pairs. The first real run needs compiled programs (#4, #7). **Logged before any eval pass**: no eval episode has been run, and no result is claimed. |
| 44 | 2026-09-30 | **The arms can share one frozen library: `bench.build_library` builds it from the admit set, and `run_benchmark(frozen_library=...)` dispatches every arm against it without writing (issue #4, ADR-0009).** Until now each arm grew its own `library-{arm}` online, so the only arm-2-versus-arm-3 number came from different libraries. The build solves each admit-set seed against its own empty scratch library, so the artifact cannot depend on either arm's dispatch, and copies every program -- admitted or rejected -- with its history into one root; its episodes go to their own ledger. The frozen mode suppresses the three online writes (compile on fallback, demotion, quarantine), still records every fire and misfire on the row, and raises if the library's hash changed by the end of the run. The online mode stays the default, for the cost curve, and §8's demotion and quarantine apply there unchanged. **Live correction:** phase 2's exit criterion said both dispatchers sweep a threshold; revision 43 and ADR-0008 made arm 3 one operating point, and the phase table now says so. **Not done:** the library is not built -- that needs a model and a key -- and #4's other items (the 2x2 admission factorial, arm 3-prime, arm 2's top-k rerank, `program_ids` per row) remain open. No eval episode has been run, and no result is claimed. |
| 45 | 2026-09-30 | **The admission factor is runnable: one compile gated twice, with "ungated" meaning positive-only (issue #4, ADR-0010).** `admit(gate=AdmissionGate.POSITIVE_ONLY)` runs the pre-sandbox contract checks and the positive side unchanged and skips only the three negative-sandbox classes, so the factor isolates Claim 3's criterion. `build_library(positive_only_root=...)` stores each compiled program in the two-sided root and gates the same program again into a second root, so the libraries differ only in what each gate admitted; each root's `build.json` records its gate, outside `library_hash`. The ledger gains `admission_gate` (`two_sided`, `positive_only`, or `None` for arm 1 and for a frozen library with no manifest), and `bench.report.admission_factorial` gives one cell per (arm, gate) over graded variant episodes, coverage and per-fire mismatch as in ADR-0008, refusing an unknown gate or a gate spread over two libraries. Arm 3-prime is the {precondition, positive-only} cell. **Live correction:** Figure 3 now says what *ungated* means and where the two libraries come from. **Not done:** the libraries are not built (a model and a key are needed), and no figure is drawn. No eval episode has been run, and no result is claimed. |
| 46 | 2026-09-30 | **Arm 2 can run as retrieve-then-rerank: a second `Similarity` rescores the first stage's top k, and its score is the one thresholded (issue #4, ADR-0011).** #4 asks for arm 2's "top-k rerank before selection"; the representation half (request plus fingerprint text) already existed, the rerank did not. The owner chose a second scorer seam over an LLM reranker, so arm 2's dispatch still makes no LLM call and its replays stay free. `Library(reranker=..., rerank_k=3)` retrieves the top k admitted programs by `similarity`, rescores them with the reranker, and thresholds, orders and records the reranker's score; `None` leaves arm 2 single-stage and unchanged. The rerank lives behind the matcher, not in `dispatch.py`. Its usage is metered into `embedding_tokens`/`embedding_calls`, rows record `rerank_k`, and `bench.coverage.arm2_outcomes` reranks the same way so the pair-level analysis measures the arm the episodes run. **Live correction:** §7's ledger schema lists `admission_gate` (ADR-0010, omitted when that field landed) and `rerank_k`. **Not decided here:** whether the eval runs with a reranker, and which — a tune-pass configuration to be recorded. No eval episode has been run, and no result is claimed. |
| 47 | 2026-09-30 | **Every row names the programs its library held (issue #4).** #4 asks that every ledger row record `library_hash` "and list the program_ids present"; the digest was recorded (#64), the list was not. `EpisodeRecord.library_program_ids` is every program id in the library as the episode found it, sorted -- every status, because the digest covers every status -- and `Library.program_ids()` produces it. It is written on normal and invalid rows alike. The `library_hash` field's docstring still said each arm grows its own library and that removing the confound was tracked separately; since ADR-0009 the frozen mode removes it, and the docstring now says so. The field is additive and defaulted; no metric changes, no eval episode has been run, and no result is claimed. |
| 48 | 2026-09-30 | **The plan runs as whole-run replicates, and seed-level uncertainty comes from an instance-clustered bootstrap instead of a mixed model (issue #6, ADR-0012).** #6 asks for k >= 3 repeats per (fault, seed, arm) and a mixed model with seed as a random effect; neither existed. The owner chose whole-run replicates -- `run_replicates` re-runs the plan from scratch per replicate, with its own ledger and, online, its own libraries, because a back-to-back repeat in one run would replay the first one's program -- and a cluster bootstrap over instances instead of a fitted model, because the repository takes no statistics dependency and a GLMM is unstable at 47 instances. Rows record `replicate`; `cluster_bootstrap` gives arm 2 minus arm 3 per-fire mismatch (ADR-0008) with a seeded 95% percentile interval over 2000 resamples of whole instances, over graded variant rows, skipping and counting resamples in which an arm fired nothing. **Live correction:** §7 item 2 still named the unit of analysis "the fault seed/family"; since ADR-0005 it is the environment, and the item now says so and names the replicates and the bootstrap. Of #6's other items, the seed split, the pairing, the pinned dates, recorded model and temperature (#133) are done, and "occurrences 2-4 as held-out variants, or relabelled replays and excluded" is met by its second branch (`occurrence_roles`); a clean rerun reproducing eval numbers needs an eval run. No eval episode has been run, and no result is claimed. |
| 49 | 2026-09-30 | **Probes must only read: one that changes the sandbox is refused, counted, and fails admission (issue #10).** #10 asks for preconditions that are "pure read-only probes"; since #108 they were screened by the guard, but the guard permits writes inside the sandbox because bodies need them, so a probe such as `git reset --hard` ran and corrupted what every later probe and the episode observed. `evaluate_predicate` now snapshots the sandbox before and after each probe (working-tree files by content, the index as `git ls-files --stage`, `.git/config`, `.git/HEAD`, and the refs of the clone and the upstream; not `.git/index`'s bytes, which `git status` legitimately rewrites) and refuses a probe that changed any part, naming it. `PredicateResult.refused` flags both a guard refusal and a mutation, and `GroundTruthResult.refusals` counts them, so a refusal no longer reads as an ordinary non-match. Admission's negative side treats a refused precondition as a defect, closing the hole where a refused probe rejected every negative sandbox and passed as a program that never fires. §9's threat table gains the row. The snapshot costs about 11 ms (three git calls), twice per probe; the Linux suite's wall clock rose from about 3.6 to 4.8 minutes. **Not done (#10):** the precondition vocabulary and breadth cap, argv templates, process isolation, and the injection suite. No eval episode has been run, and no result is claimed. |
| 50 | 2026-09-30 | **Bodies and probes run in their own process group, killed whole on timeout, under POSIX resource limits (issue #10).** #10 asks that replay run "as an unprivileged user with no network, ulimits, a disk quota, and the process group killed on timeout". `subprocess.run(timeout=...)` killed only the shell, so work it had backgrounded outlived the timeout; measured, a background writer fired after the timeout and wrote its marker. `runtime.confine.run_confined` starts each command in a new session (POSIX) or process group (Windows) and kills the group on expiry (`killpg`; `taskkill /T /F`), and on POSIX sets `RLIMIT_FSIZE` to 256 MiB and `RLIMIT_CORE` to 0. Replay and probes both go through it. §9's structural protections and residual risk are updated. **Not done:** an unprivileged user, network isolation and a disk quota need privilege a process cannot give itself; Windows has no resource limits (job objects not implemented); a body that calls `setsid` escapes the group. No eval episode has been run, and no result is claimed. |
| 51 | 2026-10-01 | **An adversarial injection suite drives hostile programs through the runtime defences and reports containment per tier (issue #10).** #10 asks for a suite that seeds injection "across commit message, filename, branch name, and issue text" and reports "injection-success and containment-breach per defence tier". `bench.injection` plants an attacker instruction as real repository content in each of the four origins and then, because there is no model here to measure steering, assumes the worst case: a `hijacked_compile` stand-in drops that instruction verbatim into a program body or precondition probe, as if the compile step were fully steered. Each measured tier (guard: network, credential/env, outside-write, force-push; hardened-git hooks; the read-only probe check; the process-group kill) plants a canary — a file outside the sandbox, a planted secret, a git hook, a backgrounded writer — and the breach check reads it; the network and force-push tiers, which cannot run without real egress or a real remote, are scored by the guard's refusal. Across the default 2 seeds × 4 vectors × 7 tiers = 56 episodes the suite reports full containment (0 breaches) with injection-success on every episode by construction, and `tests/test_injection_suite.py` pins that its breach detectors fire when a defence is removed, so "contained" is a result and not a detector that can only say yes. §9 gains the suite under structural protections. **Not measured:** the compile-time untrusted-channel tier, which needs a model; it is reported as a row with no episodes rather than silently omitted. **Vector note:** because the stand-in is fully hijacked, containment depends on the tier, not the vector, so the vector axis shows the four origins are exercised, not that origin changes the outcome. No eval episode has been run, and no result is claimed. |
| 52 | 2026-10-01 | **A program may carry argv-template `steps` instead of a shell body, run without a shell (issue #10).** #10 asks the compiler to "select and parameterize only from a fixed allowlist of argv templates ... parameters passed as argv arrays, never shell or f-strings, with per-template type+regex validation and realpath containment". `runtime.templates` adds that path: a `Program` carries either a shell `body` or a list of `steps`, each naming one entry in a closed catalogue (sync: fetch/reset/rebase/merge; submodule: update/checkout/rm/config/add/commit). `runtime.replay` dispatches on which is set; a `steps` program is built into an **argv array** per step from the sandbox's bound values and the step's literals and run with `subprocess` directly, so an attacker-controlled value — a commit message, a `.gitmodules` path — is one element git receives verbatim and cannot become code. Bound values are validated before they reach argv: refs against a charset, paths against a charset and realpath containment under the working tree (so a `.gitmodules` `path = ../../escape` is refused rather than handed to `git -- <path>`). The two hand-written gold resolution sets are migrated to `steps` and run end to end through the executor, so the catalogue is exercised, not a stub; `Program` now requires exactly one of `body`/`steps`, and admission's undeclared-parameter check (#77) reads step parameters for the typed path. §9 gains the argv-template boundary under structural protections. **Not done (#10):** the model-compiled online arms still emit shell bodies behind the guard — migrating the compile step to emit `steps` is issue #4's territory; and the precondition breadth cap and the unprivileged-user/network/disk-quota isolation remain open. No eval episode has been run, and no result is claimed. |
| 53 | 2026-10-01 | **A measured breadth cap: a precondition set that fires on more than half the sampled states is rejected (issue #10).** #10 asks for a "measured breadth cap: predicates matching >X% of sampled states are rejected, and X plus the sampling procedure are recorded." X is `agents.compile.BREADTH_CAP` = 0.50 and the sampling procedure is `sampled_states`: the clean sandbox plus one sandbox per distinct injected state of every fault, at the first seed that selects it (`variant_for_seed`), ten states in all. `precondition_breadth(program)` reports the fraction fired on, and `admit` rejects a program over the cap on the negative side. Measured and grounded, not guessed: every gold program fires on exactly one of the ten (0.10), so the cap sits far above any targeted program and rejects one firing on six or more. The three enumerated negative classes are a sharpening of this holistic cap: after a program is rejected on the clean sandbox, every unrelated fault's states and its declared siblings, only its own fault's remaining states can still fire, and no fault has more than three, so for the current family the cap does not bind — it and the recorded breadth number are the backstop that becomes load-bearing if a fault injects a state no enumerated class names. `admit` computes the cap cheaply from the own-fault remaining states (the enumerated classes already established the rest do not fire) and `precondition_breadth` does the full sweep for any program; `tests/test_breadth_cap.py` pins that the two agree and that a fire-everywhere precondition is measured over the cap and refused. §6 records the criterion. **Not done (#10):** the unprivileged-user, network-isolation and disk-quota items need privilege a process cannot give itself (CI/container work), and migrating the compile step to emit argv-template steps is #4's. No eval episode has been run, and no result is claimed. |
| 54 | 2026-10-01 | **Bodies and probes run with no network where the host allows it (issue #10).** #10 asks that replay run "with no network". `runtime.confine.run_confined` now runs each command inside a fresh, empty network namespace via `unshare --net` when the host can create one, a kernel boundary rather than the guard's textual screen; measured, an egress attempt under it is refused while local-path git (the sandbox's only remote) still works. The privilege to create a namespace may be withheld (a non-root runner, a locked-down container), so `network_isolation_available` probes for it once and, when it is absent, the command runs without the namespace and `Confined.network_isolated` / `ReplayResult.network_isolated` record that it did — the owner's choice: run and record, not refuse (so a host without the privilege, and the Windows path, are no worse off than before). The guard still screens network tools in the body, so the textual screen remains the fallback. §9 gains the mechanism under structural protections and the residual-risk paragraph is corrected: network isolation is kernel-enforced where the namespace is available, and a separate unprivileged user and a real disk quota remain the privilege-gated items #10 leaves open. `tests/test_network_isolation.py` pins egress blocked where available, the recorded fallback everywhere, and that a refused body is never recorded as isolated. No eval episode has been run, and no result is claimed. |
| 55 | 2026-10-01 | **The last two #10 isolation items are recorded as a runner requirement, not library code (ADR-0013).** #10's isolation list ends with a separate **unprivileged user** and a real **disk quota**. Both need a privilege a process cannot give itself — setuid or a user namespace to drop users, a filesystem quota or a size-capped mount for the quota — so implementing them in `runtime` would either assume a privilege the library cannot (as the root-only `unshare --net` already shows) or be a no-op that reads as a guarantee, the "stub that reads like a boundary" this repository rejects. ADR-0013 records the decision: the library enforces only process-giveable isolation, and an unattended eval against untrusted repositories MUST run inside an execution container the operator configures for a non-root user, a size-capped sandbox root, and container-level no-egress (or the namespace capability the library then uses). `docs/running-unattended.md` is the operator's half of the contract — what the library already enforces, a table of what the runner must provide and why the library cannot, and a worked `docker run --user … --network none --read-only --tmpfs` example. The library records `network_isolated` but does **not** verify the user or the quota, and the doc says so plainly so no reader mistakes a green run for a configured runner. §9's residual-risk paragraph now points at ADR-0013 and the new doc. This is documentation of the boundary, not code: no `runtime` behaviour changes, no eval episode has been run, and no result is claimed. |
| 56 | 2026-10-01 | **The first issue #7 baseline lands: a zero-token gold oracle floor (ADR-0014).** #7 asks for four baselines so an arm-3 win is attributable rather than a straw man; the first is "hand-written gold scripts as a zero-token oracle floor". `Arm.GOLD` replays, for each episode, the ground-truth variant's committed resolution (`bench/gold/`, loaded by `bench.gold.load_gold_programs` and injected into the run like the `provider` and the `similarity` seam), making no model call. It is an **oracle** — it reads the state's correct variant to pick which gold program to run — which is exactly why it is a floor: its success bounds what any arm could reach here and its zero cost bounds the cheapest an arm could be. Because it consults ground truth it is excluded from the matched-coverage dispatch comparison (`report.mismatch_comparison` still reads only arm 2 and arm 3); it flows through the arm-generic cost/success tables and the Pareto frontier, where `report` names it the floor, and it cannot misfire (it fires the correct variant by construction). `run_benchmark` refuses the run up front unless the gold set covers every measured fault's every variant (`_require_gold_covers`), so a gap in the oracle is a configuration error rather than a silent dent in the floor. §7 item 4 now lists the oracle floor among the secondary metrics. **Not done (#7):** the soft-classifier (2b), intent-key (2c) and reflexion (1b) baselines remain, each its own change. No eval episode has been run, and no result is claimed. |
| 57 | 2026-10-01 | **The second issue #7 baseline lands: arm 2c, intent-key dispatch (ADR-0015).** #7 asks for "exact/parameterized intent-key dispatch, the cheapest credible competitor": if a lookup on the request string does as well as text similarity or preconditions, the comparison between those two was not measuring what it claimed. `intent_key.intent_key` normalises a request (lower-cased; quoted strings, path-like tokens, commit ids and numbers become placeholders; punctuation dropped), and a program's key is the key of the request it was compiled from (`Provenance.compiled_from_task`). `Library.match_intent_key` returns the admitted programs under the request's key and **abstains** when they implement two or more resolutions -- the owner's choice over "last write wins" (a straw man on phrasings that recur across states) and a majority vote (scored partly on scheduling). `Arm.INTENT_KEY` runs through the same path as arms 2 and 3 -- runtime, guard, checker, fallback, compile, demotion, quarantine, frozen mode -- with no score, so it is one operating point; `bench.coverage.intent_key_outcomes` applies the same rule to labelled pairs. `bench.run`'s arm-to-matcher selection is now an explicit table that raises for an unlisted arm, where a final `else` used to run arm 3's matcher for any arm not named. Measured only as properties, not results: every shipped phrasing of both intents keeps a distinct key, and hand-written gold (whose provenance names no request) fires on none, so 2c is measured on a compiled library. §7 item 4 lists it. **Not done (#7):** the soft-classifier (2b) and reflexion (1b) baselines. No eval episode has been run, and no result is claimed. |
| 58 | 2026-10-02 | **The third issue #7 baseline lands: arm 2b, a soft vote over arm 3's own probe features, and the rule that decides whether Claim 2 is restated (ADR-0016).** #7 asks for "a soft classifier over the SAME probe features with a learned threshold -- if 2b ties arm 3, hard conjunctive executable predicates add nothing over the same information". The owner chose a soft vote: `library.soft_vote_score` is the fraction of a program's preconditions that hold, read from the same `evaluate_preconditions` results arm 3 reads `.ok` from, so arm 3 is the vote at threshold 1.0 and a test pins that the two make identical choices there on real sandboxes. `Library.rank_soft`/`match_soft` and `dispatch_soft_vote` run it behind the library seam; `Arm.SOFT_VOTE` goes through the shared dispatch path, records its score in `dispatch_score` and its threshold in the new `soft_threshold` field, and `run_benchmark` refuses a 2b run without a learned threshold rather than recording a default as if it were tuned. `bench.soft_vote` collects outcomes on real sandboxes (each seed's faulted state as a positive, its clean sandbox as a negative), learns the threshold for most correct decisions with ties to the stricter floor (the owner's choice), and `claim2_verdict` applies the new §7 item 12. **Found while building it:** on hand-written gold at the tune seeds (64 outcomes) the most accurate threshold is **1.0** -- the hard rule -- and lowering it to 0.5 fires on all 64 with 32 wrong, so a naive "equivalent at matched coverage" test would have restated Claim 2 on two arms making identical decisions; item 12 reports that case as **collapsed** and keeps the registered wording. That is an exploratory figure on gold, not the eval. `tost_equivalence` gains a `quantity` label so its reason names mismatch rates when it compares them. **Not done (#7):** the reflexion baseline (1b). No eval episode has been run, and no result is claimed. |
| 59 | 2026-10-02 | **The fourth issue #7 baseline lands: arm 1b, ReAct with a memory of its own past successes (ADR-0017).** #7 asks for "react plus prior-success memory/reflexion, the standard experience-reuse baseline whose absence makes the react curve artificially flat". The owner chose trajectories over written reflections and the model's own verdict over the checker's: `agents.memory.SuccessMemory` stores the request and the git commands that ran without error, written when `solve` returns `SUCCESS` (the model declared the task done), inside the arm and before `run_episode` runs the fault's checker, so no ground truth reaches it and a declared-but-wrong episode is remembered as a deployment's would be (a test pins exactly that). Each episode recalls the `RECALL_K = 3` most lexically similar entries (ties to the more recent; zero-similarity entries never recalled), rendered as a prelude to the **user** message with a warning that they may not apply, so the system prompt every arm sends is byte-identical and the prompt-prefix report stays true. No extra model call is made; 1b's extra cost is the longer prompt, charged through the same accounting. `Arm.REACT_MEMORY` keeps one memory per arm per run, records `memory_recalled` on its rows, has no library and no admission gate, and is refused in a frozen run, which exists so that nothing learns mid-run -- 1b is a baseline for the online cost curve. An end-to-end test runs arm 1 and 1b on the same plan and pins that 1b's second episode carries its first episode's commands while every earlier prompt carries none. With this row all four #7 baselines exist. No eval episode has been run, and no result is claimed. |
| 60 | 2026-10-02 | **Issue #4's last test item: only the dispatch function varies between arms, and admission is the only free variable (ADR-0018).** #4 asks for "tests [that] assert all arms load the same library_hash and that admission settings are the only free variable"; one test covered arms 2 and 3, and arms 2b and 2c (#153, #152) dispatch from the library too. `bench.run.DISPATCHING_ARMS` now names the arms that choose from a library (2, 3, 2b, 2c), `_dispatch` serves exactly that set, and the `admission_gate` field is derived from it, so arm 1, 1b and the gold oracle record no gate by construction rather than by a hand-kept list. `tests/test_one_free_variable.py` pins three things: the dispatch table serves exactly `DISPATCHING_ARMS` and refuses every other arm; in one frozen run every dispatching arm reads the same unchanged artifact (one hash, one program-id list, one gate, all replaying for zero tokens); and two frozen runs whose libraries differ only in the gate their build recorded produce rows that differ in `admission_gate` and in no other field the runner writes (wall-clock aside), so the 2x2's admission factor carries no confound from the harness. It also settles the design choice #4's first comment left open: `StateFingerprint.observe` reads `upstream/main`, so every fault must leave it resolvable (ADR-0018, written on `FaultSpec.inject`), and the test builds every state in `sampled_states()` -- admission's own negative universe -- and asserts the ref resolves and `observe` returns. **Not done (#4):** the frozen library is not built or committed and the factorial has not been run; both need a model and a key. No eval episode has been run, and no result is claimed. |
| 61 | 2026-10-02 | **The primary metric is reported, not only computed: Figure 1, the matched comparison and the power statement (issue #5).** #5's open items were the swept mismatch-vs-coverage curve "with Wilson confidence intervals at each operating point" and "an explicit power statement". `bench.coverage` already held the arithmetic (revision 43, ADR-0008), but nothing assembled it: no call site produced the curve, the intervals or item 3's statement. `bench.primary.primary_report` now does, for one regime at a time (refusing pooled outcomes, ADR-0004, and outcome lists from different pair sets): arm 2's `sweep` with a 95% Wilson interval on every point, arm 3's single point as the pre-registered coverage point, `matched_comparison` against it, and a power statement from `detectable_difference` at the matched fire counts -- always at a conservative 50% base rate (the least-powered case, as ADR-0006 stated its margin's power) and also at the observed pooled rate when that rate is informative. The vacuity guard from #5's design comment comes first: while `vacuous_reason` fires, `summary` prints it **instead of** the comparison and the figure's title says so. #7's dispatching baselines may be added to the plane as context, a scored one as a curve and an unscored one as a point. `write_primary_report` writes `figure1.csv` (the deliverable), `primary.txt` and `figure1.png`; Figure 1's paragraph now names it. Both arms of #5's "threshold swept for both dispatchers" are met as ADR-0008 re-defined them: arm 2 is swept, arm 3 has no score and is one point. **Not done:** the first real Figure 1 needs a compiled library's pair outcomes (#4). No eval episode has been run, and no result is claimed. |
| 62 | 2026-10-02 | **The provider sets its own timeout, and a transport failure is a retried, counted provider error (issue #157).** The first live run (#163) lost every compile call to httpx's **5-second default timeout**: `DeepSeekProvider` built its client with none, a compile reply from a reasoning model takes longer, and the build admitted nothing until the run's own driver raised the limit. `DeepSeekProvider` now takes `timeout` and `connect_timeout`, defaulting to `DEFAULT_TIMEOUT_S = 300` and `DEFAULT_CONNECT_TIMEOUT_S = 30` -- the values that smoke build completed every call under -- and wraps any `httpx.TransportError` (a timeout, a refused or reset connection) as `ProviderTransportError`, a `ProviderError` with no status, as `ProviderError`'s docstring had always described transport failures. `bench.run._is_retryable` treats it as transient and retries it under the same three-attempt cap as a 429 or 5xx; a malformed body, the other status-less failure, stays unretried. Because it is now a `ProviderError`, `_AccountingProvider` counts every timed-out attempt in `llm_calls`, which it previously could not see. §8's degradation table now says so. No eval episode has been run, and no result is claimed. |
| 63 | 2026-10-02 | **A per-invocation git config override can no longer undo the hardening (issue #159).** The first live run (#163) found, and a reproduction then verified, that `git -c core.hooksPath=<dir>` runs hooks from `<dir>` under the hardened environment, because command-line config wins over the `GIT_CONFIG_COUNT` pins; the replay guard allowed such a body, and the ReAct tool's `run_git` let the live agent use `-c` freely. `sandbox.git_config_overrides` now parses git's **global** options only -- so `git log -c` (a combined diff) is not mistaken for config -- across every nested `git` in a command, including a `submodule foreach` command given as one quoted string; `disallowed_git_config_overrides` compares them case-insensitively against `ALLOWED_GIT_CONFIG_OVERRIDES`, an allowlist of exactly `protocol.file.allow=always` (the local-file transport the submodule family needs), with `--config-env` never allowed because its value cannot be vetted. The guard refuses any disallowed override and any body that sets a `GIT_CONFIG*` variable in its own environment (which would replace the pins outright); `run_git` refuses the same overrides. A persistent repository `git config core.hooksPath` write was verified **not** to beat the hardening and is left alone. The injection suite gains a `git_config_override` tier -- a hook committed as ordinary work-tree content and a body pointing git at it -- contained by the guard, with a control test showing the same command fires the hook under the hardening alone. §9's threat table gains the row. No eval episode has been run, and no result is claimed. |
| 64 | 2026-10-02 | **Admission judges an overlap state by the program's own intent, not as unrelated (issue #158, ADR-0019).** The first live build (#163) rejected every compiled diverged program on `lockfile_conflict` seed 0, counted as an *unrelated* state where any fire is a defect -- but that state is a diverged branch whose two sides touched one file, and the sync intent's own `decided_by` labels it **merge**. The negative set held a state the task family's own labels call correct for a merge program, so the gate rejected correct programs; the hand-written gold merge program passed only through the `local_work_beyond_the_overlap` precondition, added earlier to dodge this exact state. Owner's choice: `admit` now labels each unrelated-fault state with this program's intent (`_preconditions_accept_labelled`, one sandbox build for both the label and the probes). A state the intent labels is an **overlap state**, judged like a sibling: a fire is correct when the program implements the label, a mismatch otherwise; only an unlabelled state stays unrelated, where any fire is a defect. Correct overlap fires count toward the breadth cap. `tests/test_overlap_states.py` pins the overlap itself, that gold merge minus the workaround precondition is now **admitted**, that the same program labelled `rebase` is **rejected** with the overlap reason, and that gold merge still passes. The negative-class diagram in §5 says so. The submodule intent's rules are also fixed here, because this decision depends on them: they labelled a repository with no submodule `init` -- `observe` reports a missing submodule as not initialised and still referenced upstream -- which made every diverged state and the clean sandbox an `init` overlap state for a submodule program. Each rule now first requires `has_submodule_reference`; every declared grid state already has one, so no grid label moves. No eval episode has been run, and no result is claimed. |
| 65 | 2026-10-02 | **The agent's budget counts commands as well as turns, rows record tool calls, and only a declared success is compiled (issue #160, ADR-0020).** In the first live run (#163) the model issued 4-5 tool calls per turn, so the 12-turn `max_steps` let one episode run about 45 commands and another 12, depending only on batching; all four submodule solves used up the budget, and those FAIL transcripts were still compiled -- two admitted. Owner's choices: `agents.react.solve` keeps the 12-turn budget and adds `DEFAULT_MAX_TOOL_CALLS = 24` (twice the turn budget, so a one-call-per-turn agent never meets it first), stopping with `FAIL` once that many calls have run however they were batched; every row records `tool_calls`, refused calls included, beside `llm_calls`; and `_run_arm` marks a fallback `compilable` only when the agent itself returned `SUCCESS` -- the agent's verdict, which the no-oracle rule allows, not the checker's. `tests/test_tool_call_budget.py` pins the cap against one 30-call turn, the recorded count on a batched solve, and that a failed solve triggers no compile call. §7's ledger schema lists `tool_calls`. No eval episode has been run, and no result is claimed. |
| 66 | 2026-10-02 | **The harness keeps no bookkeeping in the clone (issue #161, ADR-0021).** The first live run (#163) found the ReAct agent reading `refs/sandbox/submodule-path`, `refs/sandbox/refs-at-start` and `refs/sandbox/injected` -- the three refs #103 had left in the clone. A precondition anchored on one holds in every sandbox and in no real repository, and `refs-at-start` is a ready-made diff of the injection. All three move into `Sandbox.recorded`: `require_uninjected` reads the recorded `base`, reversing revision 24's on-disk marker (a `Sandbox` is only built by `create`, so the in-memory record lives as long as the sandbox); `submodule_moved` records `RECORDED_SUBMODULE_PATH`, and `submodule_path` now takes the `Sandbox`; `tasks.invariants` holds `RECORDED_REFS_AT_START`. `store_blob` has no caller left and is removed. `recorded_state_intact`'s "every `refs/sandbox/*` ref still resolves" clause, which doubled as the re-clone detector, becomes "every object a work ref named at the start is still in the object store"; that is weaker for a fault whose starting commits are all on upstream (`dirty_tree`), where the fault's own checker still catches the loss. `tests/test_harness_record_outside_clone.py` pins that no fault leaves a `refs/sandbox/` ref in either repository at seeds 0 and 1, that a second injection is still refused, and that `{submodule_path}` still binds after a correct removal; `tests/test_non_destructive_invariants.py` pins the re-clone violation and a `reset --hard` control. No committed content changes, so no commit SHA moves. No metric definition, denominator or reported number changes and no result is claimed. |
| 67 | 2026-10-02 | **Figure 1's pair outcomes come from a compiled library's own matchers on real sandboxes (issue #162, ADR-0022).** The first real Figure 1 (#163) needed a driver outside the repository, because `coverage.arm2_outcomes` takes one text per variant and `arm3_outcomes` a caller-supplied decision. `bench.library_pairs.library_pair_outcomes(library, faults, seeds)` builds each pair's sandbox and returns one `PairOutcome` list per dispatcher, index-aligned with the pairs: arm 2 through `match_semantic` with no floor (the library's configured threshold is not applied, so `sweep` sees every score), arm 3 through `match_preconditions`, 2b through `rank_soft` with its score, and 2c through `match_intent_key`; the signature is built as `bench.run` builds it, the request is the uninformed one the episodes send, and the library is never written. Each measured intent's request is paired with its own fault's state, the fault-free sandbox, and another fault's state only when the intent labels it. An unlabelled foreign state is not a pair (`is_pair`): the first version included those as negatives, and arm 3, which reads only the environment by design, fired the sync program on diverged states under the submodule request, which no episode poses. Building the pairs also found that the submodule intent labelled a repository with no submodule `init`; that is fixed in #158's change, revision 64. `arm2_outcomes` and `arm3_outcomes` stay for the declared grid and the gold probe. `tests/test_library_pairs.py` pins the pair set, that gold arm 3 is the labelling rule (so `vacuous_reason` fires), that arm 2 is unthresholded under a 0.9 library floor, that a candidate program never fires, that 2c fires on a program compiled from the pair's request, the inclusion rule on its own, and that the result feeds `primary_report`. No eval episode has been run, and no result is claimed. |
| 68 | 2026-10-02 | **A live run is one committed command (#163).** The first live run went through a driver outside the repository, so the run that found #157-#162 could not be repeated from what is committed. `bench.live` is that driver, committed. `python -m precondition_library.bench.live --out DIR` runs, in order: `build_library` on the smoke seeds into a two-sided and a positive-only root (ADR-0009/0010); `learn_soft_threshold` on the tune seeds; `run_benchmark` with every frozen arm against the two-sided root, and arms 2 and 3 against the positive-only root; `write_report` on the two-sided ledger only, so the main tables never mix two libraries' rows for one arm; `admission_factorial` on the two ledgers concatenated; `library_pair_outcomes` and `primary_report` for Figure 1 on the eval seeds, with 2b's `claim2_verdict`; and, unless `--skip-online`, arms 1 and 1b online. The output directory must not exist. `summary.json` and `summary.txt` record the plan, the admitted counts, the library hash, the learned 2b threshold, the Claim-2 wording, Figure 1's summary, the factorial cells and every artifact's path. The key's source is named by the caller, `--api-key-env NAME` or `--api-key-file PATH`, exactly one, never the key itself, and nothing prints or writes it; the package still finds no key on its own. `--episode-seeds` defaults to the first live run's 4 eval seeds. `tests/test_live_run.py` replaces the two model-calling stages with recording stand-ins and runs the rest for real on admitted gold: the stage order, the library each benchmark ran against, that 2b runs at the learned floor, that 1b is online only, that the report reads one ledger, Figure 1's vacuity on gold, the summary files, the fresh-directory refusal, and the key handling. No live run has been made with it, and no result is claimed. |
| 69 | 2026-10-02 | **A live run whose build admits nothing stops cleanly and says why (#173).** The second live run's build admitted none of its three compiled programs (#171, #172), so `bench.live` reached the frozen benchmark, `run_benchmark` refused the empty library, and the command exited with a traceback and no summary. Now the summary is always written, and every summary carries `build`: one entry per build episode with its outcome, tool calls, the checker's verdict, whether it was admitted, and the gate's `compile_failure_reason`, or `not compiled: the agent did not declare the task done` for a FAIL that #160 kept out of the library. When the two-sided library admitted nothing, the 2b tuning, the frozen benchmark, the factorial and Figure 1 are skipped, because they have nothing to dispatch. `stopped_after` is `build` with a stated `stop_reason`. The online arms 1 and 1b still run, since they need no frozen library. The command then prints the summary and exits 1 with a one-line message. `tests/test_live_run.py` pins the per-episode build lines, the skipped stages, that the online arms still ran, the summary files, and the exit code. No live run has been made with it, and no result is claimed. |
| 70 | 2026-10-02 | **A mismatch is a fire outside the resolutions a state accepts, not a fire other than its label (issue #172, ADR-0023).** The second live run (#163) found the model rebasing successfully on `merge`-labelled diverged states, and every resulting `rebase` program rejected as a mismatch. The labels named one resolution per state; the checker grades the outcome, not the method. Owner's choice: **multiple** acceptable resolutions. Measured before the change, by replaying every gold body on every state over 60 seeds: on `diverged`, merge and rebase pass the checker in every state, and discard passes only where it is the label; on `submodule_moved`, exactly one passes per state, and it is the label. `ResolutionVariant.accepted_by` declares where else a resolution is acceptable, and `IntentSpec.acceptable_variants(state)` returns the label plus those, or `()` for an unlabelled state. `program.accepts` is the one rule every scorer applies: the pair metric (`LabelledPair` and `PairOutcome` carry the set, which drives `operating_point`'s mismatch and `vacuous_reason`), the 2b tuning, the ledger's `misfired` (rows record `acceptable_variants`; an old row without it reads as the label alone), online demotion's mismatch count, and admission's sibling and overlap classes, where a fire on a state that accepts the program's resolution is correct and counts toward the breadth cap. **Consequence:** on `diverged` the only wrong fire left is `discard` on a state with real local work, so the intent tests whether a dispatcher avoids the destructive resolution, not which of three it picks; `submodule_moved` is unchanged and remains a three-way choice. The text-similarity probes (`bench.similarity_probe`, `bench.textcontrol`) and their recorded baselines (ADR-0003, ADR-0004, ADR-0007) keep scoring against the single label: they measure whether text predicts the label, and nothing they report is recomputed. `tests/test_acceptable_variants.py` replays every gold body on every injected state and requires the checker's verdict to equal the declared set; the tests that pinned `rebase`-on-`merge` as wrong now pin `discard` on a `merge` state instead. No eval episode has been run, and no result is claimed. |

---

## 1. Summary

An LLM agent re-derives the same solution every time it meets the same problem.
This project builds an agent that solves a task once, compiles its solution into
a persistent **program**, and then replays that program on later occurrences
**with zero LLM calls**.

The uncontroversial half is the amortization: cost is paid once and spread
across recurrences. The contestable half — and the reason this is a research
project rather than a caching exercise — is **how the agent decides a stored
program still applies**:

| | mechanism | nature |
| --- | --- | --- |
| arm 2 | similarity between the new task and the one that produced the program | probabilistic |
| arm 3 | the program's own **executable preconditions** accept the environment | checkable |

### Claims

**What this project does not claim.** Added 2026-09-13 after the prior-art sweep;
ADR-0001 records the reasoning and the source-checked citations.

- Not that compiling a task into a persistent program and replaying it cheaply is
  novel — PreAct, SkillDroid, Auto, and LATM all do it.
- Not that dispatching a cached plan by executable preconditions is a novel
  mechanism — it is MACROPS, 1972, with an explicit replan fallback.
- Not that "the most similar case is not the most reusable" is new — Smyth &
  Keane, 1998.

**Claim 1 (context, not a contribution).** Tokens and LLM calls per episode fall
across repeated occurrences for the compiled arms and stay flat for the ReAct
baseline, **read off the cumulative amortized curve with its break-even marked**
(Figure 2) — with the arm triple reported alongside: success rate, tokens per
episode and **cost per success** (§7 item 8), since an arm that succeeds more often
may legitimately spend more. Two limits are part of the claim rather than caveats
around it:

- **It is a claim about tokens and calls, not about currency.** No cost figure is
  reported, because pricing input correctly needs a rate table and DeepSeek's rates
  differ by peak and off-peak hours, so the rate or the call time would have to be
  recorded per episode (§7's ledger bullet). Input is metered as uncached,
  cache-read and cache-write so a cost figure can be computed once rates exist;
  until then the figure is tokens.
- **"Equal success rate" is not available to it.** Comparing the two dispatch arms'
  success rates requires the pre-registered equivalence test (§7 item 10); where it
  does not pass, the text says "comparable success rate". No episode has been run,
  so nothing is equal or comparable yet.

This is an engineering assumption and a cost model. It is established prior art and
is never presented as a finding.

**Claim 2 (primary, empirical form).** At **matched dispatch coverage**,
executable-precondition dispatch is *expected* to mis-fire less often than
text-similarity dispatch — a mis-fire being a program that runs, claims success,
and did not — with mismatch logged independently of episode success. The mechanism is
classical; what has not been measured is the comparison. Whether the expectation
holds is the open question: §7 pre-registers the analysis, §13 lists the works
that bracket it without answering it, and **no result exists yet**. This is the
only *measurement* prior art does not settle.

**Claim 3 (artifact-level).** A negative-sandbox admission criterion — admit a
program only if it passes postconditions on a faulted instance **and** fails its
preconditions on generated negative states — is a requirement that **no confirmed
work publishes**; the closest published gate is exit-condition-based and applied
as a cascade after semantic recall, which is a different test. Cheapness and
enforceability are design intentions, not findings. Reported as a 2×2 factor
against an otherwise identical positive-only gate.

The claim structure changed because the original primary claim was untestable as
designed: with one fixed task sentence per fault, the task text *was* the
ground-truth label, so similarity dispatch could not mis-fire by construction.
Analysing it would have produced a number that looked like a result while
measuring nothing.

### What would falsify this

- **No difference at any coverage.** Then the finding is that executable
  preconditions buy no dispatch accuracy over text similarity in this domain, and
  the negative-sandbox admission factor (Claim 3) becomes the contribution.
- **The injected faults leak a marker.** If faults are recognisable from the task
  text, similarity dispatch wins for the wrong reason. A phrasing that names a
  resolution is rejected directly (`test_no_phrasing_names_a_resolution` matches
  whole-word variant ids in both wording channels), which is the case the AUC gates
  cannot see: the uninformed AUC is fixed at 0.500 by construction whatever the
  words say. A paraphrase that reveals the answer without naming it is a review
  obligation, not a test (§10).
- **Probes encode the answer.** If authoring the precondition vocabulary requires
  the knowledge being measured, the comparison is confounded by author effort
  rather than measured.
- **Compiled programs rot as repositories drift.** Then program mortality, not
  dispatch accuracy, becomes the finding.
- **Amortization never pays.** Compilation costs more than it saves at any
  realistic recurrence count. This no longer threatens a claim — Claim 1 is not
  claimed — it only makes the harness uneconomical.

---

## 2. Goals and non-goals

### Goals

1. A falsifiable, measurable comparison between similarity and
   precondition-gated dispatch, with a baseline an unsympathetic reviewer
   accepts.
2. A working agent that solves branchy git maintenance chores.
3. An experiment affordable for one person in 2–3 weeks, with a pre-registered
   decision rule so the analysis cannot be reverse-engineered from the results.
4. A committed program library whose git history is itself evidence.

### Non-goals

- A product, a UI, or a DSH plugin. (A plugin wrapper is a *possible* phase 6,
  deliberately out of scope — see §12.)
- Beating a frontier model on general agentic tasks.
- Claiming that compiled programs are safe to run against real repositories.
  They are not, and the design exists to keep them off real repositories (§9).
- Local-model support. The provider boundary permits it; nothing implements it.

---

## 3. The task family

### Selection criteria

A fault is admissible only if it satisfies all three. These are load-bearing,
not preferences:

1. **It recurs.** Amortization needs a second occurrence; a one-off task can
   never exercise the amortization cost model, so it cannot inform even the
   secondary concern.
2. **Correctness is checkable without a model.** If scoring an episode requires
   an LLM, scoring costs exactly what the project exists to avoid paying, and
   the cost comparison becomes circular.
3. **It is branchy.** A fault solvable by one aliased command has a *baseline
   cost of zero*, so there is nothing to save. This criterion excludes most
   obvious "agent does devops" tasks and is the reason the family below is
   narrow.

### The five faults

| fault | why it recurs | why it is branchy |
| --- | --- | --- |
| `dirty_tree` | syncing a fork with local work in progress is routine | correct recovery depends on whether the edit conflicts with upstream's changes |
| `diverged` | local and upstream both moved | merge vs rebase vs reset depends on whether local commits are worth keeping |
| `branch_renamed` | upstream renames a default branch once, then forks stay broken | requires detecting the disappearance of a remote-tracking branch and re-pointing the local one |
| `submodule_moved` | submodule pins drift constantly in fork-heavy repos | recovery differs by whether the submodule is initialised, dirty, or absent |
| `lockfile_conflict` | dependency bumps conflict in generated files | the right fix is regeneration, not marker-editing — and marker-editing *appears* to succeed |

`lockfile_conflict` is included as much for the **negative sandboxes** it
supplies as for its positive ones: it is the fault most likely to produce a
program that reports success while being wrong, which is precisely the failure
Claim 2 measures.

### Intents and resolutions (revised 2026-09-13)

A fault's request text used to be one fixed sentence, which made the text a
perfect class label and the primary claim untestable. The task family is now
described by **intents**, each carrying a paraphrase distribution and one or more
**resolutions** decided only by observable state:

| intent | resolutions | decided by |
| --- | --- | --- |
| `sync_fork_with_upstream` | discard / rebase / merge | whether local-only commits change files at all, and whether they touch files upstream also changed |
| `restore_submodule_state` | init / repin / remove | whether the submodule is initialised, whether upstream still references it, whether the recorded pin matches |

Only intents with two or more resolutions have an experimental surface, and
`tasks/registry.py` is the single place that distinction lives, so an
unambiguous intent cannot be counted into a dispatch rate as if it were evidence.
A resolution is `None` for a *benign* state — nothing to do — and such pairs are
labelled negatives, because a dispatcher that always fires can only be caught by
states that require refusal.

**A resolution is defined by the task family, not inferred from the outcome.**
That matters for one state, and knowing it prevents a misreading of the misfire
rate: on `overlapping_files` the intent requires `merge`, but a `rebase` there also
preserves the work and reaches a synced tree, so the outcome checker cannot tell
them apart — only `discard` is rejected, because only `discard` loses work. The
requirement is the policy itself: shared history is not rewritten when both sides
touched the same file. A dispatcher firing `rebase` on that state is therefore a
misfire **against the label**, and it is scored independently of the episode's
success, which is why the record stores the two as separate facts (§7). Read the
misfire rate as disagreement with the required resolution, not as a count of
destroyed work.

The request text is sampled deterministically from the paraphrase distribution
(`sha256` over the seed, never `hash()`, which CPython salts per process). When the
state is already known, `variant_phrasings` may supply *informed* wording that
reveals the situation to a careful reader, as a real user's description often does;
state may reach the request only through that declared map. The fraction of
sampled uninformed requests that name the fault is documented and asserted:
`sync_fork_with_upstream` 0.000 over seeds 0–49 and `restore_submodule_state`
0.060 over 0–49 and 0.125 over 0–199, both at ≤ 0.35
(`tests/test_intent_ambiguity.py`).

#### The boundary condition

The request text has two declared channels, and the primary claim is measured on
only one of them:

- **uninformed** — the shared `phrasings` list: what someone says when they do not
  know what is wrong, or when nothing is wrong.
- **informed** — a resolution's `variant_phrasings` entry: wording that reveals
  the situation.

How far the text alone gets a dispatcher is measured on the informed channel
rather than assumed; on the uninformed channel it is fixed by construction.
`bench/textcontrol.py` trains a bag-of-words logistic regression on the request
text alone and reports AUC per intent and regime, over the state grid in
`tests/conftest.py`, with train n=120 and eval n=120 on disjoint, enforced seed
sets (overlap raises):

| intent | uninformed AUC | informed AUC |
| --- | --- | --- |
| `sync_fork_with_upstream` | 0.500 | 0.962 |
| `restore_submodule_state` | 0.500 | 0.945 |

**On uninformed requests the text cannot carry the resolution (AUC 0.500), by
construction and not by measurement: the sampler never consults state, so every
state receives the same text for a given seed, every positive has a negative with
an identical score, and the AUC is 0.500 for any classifier and any phrasing
list — including a deliberately leaky one. The test on that regime is a plumbing
tripwire: it fails if the sampler starts consulting state, the regression that
would restore the original flaw, and it cannot certify the phrasing
distribution. On informed requests the wording nearly determines the resolution
(AUC ≈ 0.95, measured by `bench/textcontrol.py`), which is the boundary condition
where the mechanism is not needed.** An earlier draft pooled the two regimes into
one number (0.795–0.801, the pooled figures from the control's pre-split
revision) that described neither — it averaged a regime in which the text is the
answer in disguise with one in which it is noise — and that is why the split
exists.

The uninformed regime is the one gated by `LEAKAGE_CEILING`, as a tripwire for
state reaching the sampler rather than as a leak detector; the informed AUC is
reported as the boundary condition and never gated. The per-intent AUCs must be
reported together with the informed/uninformed mixture of the pairs, because that
mixture is what makes the numbers interpretable.

### Out of scope for the family

Anything requiring credentials, network access to real GitHub, or judgement
("tidy up this README"). Every fault is injected locally, solved locally, and
verified locally.

---

## 4. Architecture

Boundaries matter more than internals here: the experiment is only interpretable
if arms differ in *exactly one* component.

```
                    ┌──────────────────────────┐
                    │  bench/run.py            │  episodes × arms
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
      ┌───────▼──────┐   ┌───────▼───────┐  ┌───────▼────────┐
      │ agents/react │   │ agents/       │  │ agents/        │
      │  (arm 1)     │   │ dispatch      │  │ dispatch       │
      │              │   │ semantic      │  │ preconditions  │
      │              │   │  (arm 2)      │  │  (arm 3)       │
      └───────┬──────┘   └───────┬───────┘  └───────┬────────┘
              │                  │                  │
              │            ┌─────▼──────┐           │
              │            │ library.py │◄──────────┘
              │            └─────┬──────┘
              │                  │ programs
      ┌───────▼──────────────────▼───────────────────────┐
      │ runtime/replay.py + runtime/guard.py             │
      │   ▲                                              │
      │   │  MUST NOT be able to reach provider.py        │
      └───┼──────────────────────────────────────────────┘
          │
   ┌──────▼───────┐   ┌──────────────┐   ┌────────────────┐
   │ sandbox.py   │   │ tasks/faults │   │ provider.py    │
   │ throwaway    │   │ seeded       │   │ the ONLY place │
   │ repos        │   │ injectors    │   │ that calls LLM │
   └──────────────┘   └──────────────┘   └────────────────┘
```

**The only difference between arms 2 and 3 is which dispatch function calls into
the library.** Everything downstream — admission, replay runtime, guard, ground
truth checker, ledger — is shared code. A difference in outcome is therefore
attributable to dispatch and not to the rest of the pipeline. This is a design
constraint, not a description of the current layout: if arms 2 and 3 ever need
different runtime code, the comparison has been compromised and the design has
failed.

| module | responsibility | depends on |
| --- | --- | --- |
| `program.py` | the `Program` model: intent, parameters, preconditions, body, postconditions, provenance, status | nothing (pure data) |
| `provider.py` | the only LLM boundary; returns real token usage | httpx |
| `signatures.py` | how a task and its environment state are described | — |
| `sandbox.py` | build/destroy disposable repo + bare upstream | git |
| `tasks/faults/*` | seeded fault injection, task text, ground-truth checker | sandbox |
| `library.py` | storage, two-sided admission, both dispatch strategies | program |
| `agents/react.py` | arm 1: the ReAct-style baseline (Yao et al., ICLR 2023) — observe → act → observe | provider, sandbox |
| `agents/compile.py` | solved task → candidate program; admission gate | provider |
| `agents/dispatch.py` | arms 2 and 3 — **the experiment** | library |
| `runtime/guard.py` | screens model-authored bodies before execution | — |
| `runtime/replay.py` | executes programs, re-checks postconditions; **cannot reach `provider`** | guard |
| `bench/ledger.py` | the episode record | — |
| `bench/run.py` | episode scheduling, repeat structure | all of the above |
| `bench/report.py` | ablation table, cost curve, mismatch comparison | ledger |

### Data flow of one episode

```
seed ──▶ fault.inject ──▶ sandbox ──▶ fault.task_text ──▶ request
                                            │
                    ┌───────────────────────┴────────────────────┐
                    │                                            │
              arm 1: ReAct loop                    arms 2/3: dispatch
              (LLM every step)                            │
                    │                        ┌────────────┴────────────┐
                    │                    hit │                         │ miss
                    │                        ▼                         ▼
                    │                 replay(program)          solve with LLM
                    │                 (ZERO tokens)                    │
                    │                        │                  compile → admit
                    │                        │                         │
                    └────────────────────────┴─────────────┬───────────┘
                                                           ▼
                                             fault.check ──▶ outcome
                                                           ▼
                                                    ledger.append
```

---

## 5. The `Program` artifact

```yaml
id: sync-fork-dirty-tree
intent: bring a fork into sync with upstream while preserving uncommitted work
parameters: [work_dir, upstream_remote, upstream_branch]

preconditions:                      # executable probes; ALL must hold to fire
  - name: has_uncommitted_changes
    probe: 'test -n "$(git status --porcelain)"'
  - name: upstream_is_ahead
    probe: 'test "$(git rev-list --count HEAD..{upstream_remote}/{upstream_branch})" -gt 0'
  - name: not_mid_rebase
    probe: 'test ! -d .git/rebase-merge'

body: |                             # model-authored; runs unattended later
  git stash push -u -m pl-sync
  git fetch {upstream_remote}
  git rebase {upstream_remote}/{upstream_branch}
  git stash pop

postconditions:
  - name: upstream_contained
    probe: 'git merge-base --is-ancestor {upstream_remote}/{upstream_branch} HEAD'
  - name: no_residual_changes
    probe: 'test -z "$(git status --porcelain)"'

provenance:
  compiled_from_task: "My local uncommitted work must survive, and this fork needs to be in sync."
  model: deepseek-flash
  episode_id: react/dirty_tree/seed-12
  fault: dirty_tree          # the family whose states this program serves
status: candidate            # not yet admitted; see the caveat below
```

Preconditions are **shell probes**, not prose and not Python callables. Probes
survive serialization into the committed library, are reviewable in a diff, and
can be executed by the runtime without importing program code. A reviewer can
verify a dispatch decision by hand, which would not be true of a similarity
score.

Parameters keep one program applicable to many repositories: the library stores
*knowledge*, not a transcript of one repository's history.

**Illustrative caveat:** the YAML above is a shape, not an admitted program. The
body in particular is not claimed correct — `git stash pop` after a rebase can
conflict, and a real program would have to handle that. No program has yet been
through admission.

### Lifecycle

```text
candidate ──admission passes──▶ admitted ──postconditions fail──▶ demoted
(stored, status=candidate)         │
    │                              │ two wrong-variant fires
    └──admission fails──▶ stays    ▼
         stored (candidate;    quarantined
          rejection recorded)  (withdrawn from dispatch; retained for analysis)
```

The two mismatches are counted over the ledger's own definition: a fire whose
`fired_variant` is not the state's ground truth, *whether or not the episode
succeeded*. That is why the count is needed at all — a program that fires the
wrong resolution and still satisfies its postconditions is never demoted, and a
demoted program is already withdrawn (both matchers return only `admitted`), so
it can never accumulate the second mismatch. The load-time variant check is the
other route into `quarantined`. It keys on `provenance.fault`, not on `intent`: a
compiled program's intent is prose, so a check keyed on it would protect only the
hand-written artifacts. `Library.load_all` applies the verdict in memory and
writes nothing — a read that reparsed the library must not mutate it, and
`library_hash` loads every program — while `Library.quarantine_undeclared()` is
the explicit write that records the status and its reason (issues #66, #69).

Nothing is deleted. A program that mis-fired is the evidence for Claim 2's
numerator, and removing it would erase the result. A candidate is written to the
library **before** the gate runs, so a program that fails admission keeps its
`status=candidate` and stays as a rejected record rather than being removed. That
rejection is itself evidence — the mismatch analysis needs it — and the episode
keeps its token cost.

---

## 6. Admission: the two-sided gate

A program becomes replayable only when **both** halves of its contract are
demonstrated:

```
DECLARED   before any sandbox: every `{name}` the body uses is named by at least
           one precondition's probe. A precondition is not only how a program
           decides *whether* to fire; it is how the program declares what it
           needs, and a state it may fire in need not bind an undeclared
           parameter. A body parameter no precondition names -> not admitted,
           with the parameter named (issue #77).

POSITIVE   on N freshly faulted sandboxes: body runs, postconditions hold.
           Failure -> not admitted.

NEGATIVE   on sandboxes it must NOT claim, the preconditions must REJECT it.
           Three classes are built, from cheapest and broadest to narrowest:

             fault-free          a clean worktree with upstream already merged
                                 (`build_sandbox(seed, [])`): nothing needs doing,
                                 so every program must refuse it. A precondition
                                 set that accepts it is a DEFECT, not a
                                 convenience.
             unrelated fault     every other fault's injected states: one seed
                                 per distinct state the injector can select
                                 (`FaultSpec.variant_for_seed`), so a fault with
                                 several states is probed in each rather than at
                                 one fixed seed -- states this program's intent
                                 has nothing to do with. Except an OVERLAP state:
                                 one this intent's own decision rule labels (e.g.
                                 `lockfile_conflict`'s diverged branch, which the
                                 sync intent calls `merge`). It is judged like a
                                 sibling: firing is correct if the program's
                                 resolution is one the state accepts, a mismatch
                                 otherwise (issue #158, ADR-0019, ADR-0023).
             sibling resolution  the program's own fault, injected at a seed whose
                                 state a *different* resolution of the same intent
                                 is the label. Firing there is a mismatch unless the
                                 state also accepts the program's resolution -- the
                                 fault's checker passes it there -- and then it is a
                                 correct fire that counts toward the breadth cap
                                 (ADR-0023: merge and rebase on any diverged state).

           Each rejection names the class that rejected it and the number of
           states that class checked, so a reader can tell how much of the gate
           actually ran. A program that accepts any of these fires where firing is
           wrong, which is exactly the mismatch failure this project measures.

BREADTH    a measured cap over the whole sampled universe (clean plus one sandbox
           per distinct state of every fault): the fraction of states the
           preconditions fire on must not exceed `BREADTH_CAP` = 0.50 (issue #10).
           A set that matches most states is not targeted. Measured, every gold
           program fires on one of the ten sampled states (0.10). The three
           enumerated classes above are a sharpening of this: after they reject
           the clean, unrelated and sibling states, only the program's own fault's
           remaining states can still fire, so for the current family the cap does
           not bind -- it is the holistic backstop, and the recorded breadth
           number (`agents.compile.precondition_breadth`), that become load-bearing
           if a fault injects a state no enumerated class names.
```

The negative half is what makes Claim 2 testable. Without it, arm 3's advantage
would be an artifact of admitting programs freely and merely hoping their
preconditions were specific. Admission failures are recorded with reasons: a
high rejection rate is a finding about the compile step's ability to write
specific preconditions, not an inconvenience to be suppressed.

---

## 7. Measurement

### Ledger

One JSONL line per episode; every number reported is a grouping over this file.

```
{arm, task_id, fault_type, occurrence_index, occurrence_role, seed,
 tokens_in, tokens_out, uncached_tokens_in, cached_tokens_in, cache_write_tokens_in,
 llm_calls, tool_calls, wall_clock_s,
 outcome: success|fail|fallback|refusal|invalid, timed_out,
 correct_variant, fired_variant, ground_truth_ok, recorded_state_intact,
 program_id, dispatch_score, admitted,
 refusal_reason, compile_failure_reason, invalid_reason, replay_failure_reason, model,
 temperature, admission_gate, rerank_k}
```

- `occurrence_index` — 1 for the first time this fault type is seen, 2 for the
  second, and so on. Grouping by it produces the headline curve.
- `occurrence_role` — `variant` for the first occurrence of an **instance** of
  this fault, `replay` only on a genuine repeat of one (ADR-0005; before it the
  key was the resolution, which made same-resolution seeds — byte-identical
  environments — one observation counted many times). Declared by
  `bench/splits.py` from the injector's own seed-to-instance mapping and written
  onto every row by
  `bench/run.py`; required, with no default. **The two analyses need different
  occurrences.** The cost curve is only meaningful on the replays, because a
  variant is the first sight of an instance and no program can have been admitted
  from it yet — the curve bends exactly where an instance recurs. The mismatch
  comparison is only meaningful on the variants, because a replay's instance was
  introduced by an earlier occurrence and the program that answers it was
  admitted there, so counting a replay counts one observation twice. It records
  the plan's role and not what happened: a row labelled `replay` may still have
  paid full price, because no program was admitted for its state or the one that
  fired was refused. `llm_calls`, `outcome` and `fired_variant` say what
  happened. A reader who does not know this will compute the curve over the
  occurrences where it cannot bend, or an interval over one observation counted
  many times.
- **Input tokens are metered in three components, and none of them is a total.**
  `uncached_tokens_in` is what the provider billed at the full input rate,
  `cached_tokens_in` is the **cache-read** component, and `cache_write_tokens_in` is
  what was written to the cache. `tokens_in` is the provider's own reported total —
  their sum — and is kept so the split can be checked against it, **never as a billing
  basis**: DeepSeek publishes cache-hit input at 1/50th of cache-miss input, so pricing
  the total at one rate overstates any arm that caches, and arm 1 is the arm whose
  prompt grows with the transcript. Derived as: `prompt_cache_miss_tokens` when the
  provider publishes it (DeepSeek does), otherwise `prompt_tokens - cache hits`,
  saturating so a provider reporting more hits than prompt tokens cannot make it
  negative. **Per provider:** OpenAI-style APIs report `prompt_tokens` *including*
  cached tokens, so it is never the uncached count; Anthropic-style APIs report the
  cached portions as their own fields and bill a separate cache write, which is why
  `cache_write_tokens_in` exists even though DeepSeek always writes zero. Pricing the
  three at published rates is a separate step and is not implemented — it needs a rate
  table, and DeepSeek's rates also differ by peak and off-peak hours, so a correct
  figure needs the rate (or the call time) recorded per episode rather than applied
  afterwards.
- **Correctness is derived, not stored.** `correct_variant` is the ground truth for
  the state (from the intent's decision rules, in separate code from the programs'
  probe strings), `fired_variant` is what the program that ran actually resolves,
  and `ground_truth_ok` is whether the environment reached the expected state.
  `misfired` and `succeeded` are computed from those, so the quadrant that matters —
  a wrong fire in an episode that nevertheless succeeded via the fallback — is
  expressible. A stored outcome could not hold both halves without the two
  disagreeing, and `outcome` therefore records only how the mechanism completed.
- **Spec-gaming is derived from a fact, like the other correctness verdicts.**
  **A checker's selector comes from the harness, not from the clone.** A fault with
  more than one injected state needs to know which clause applies, and `submodule_moved`
  used to read that from a recorded `refs/sandbox/submodule-state` — a plaintext label
  inside the environment the graded code reads, so a precondition could be
  `test "$(git cat-file -p refs/sandbox/submodule-state)" = "remove"` and dispatch
  correctly without diagnosing anything (issue #103). The state now travels on the
  `Sandbox` object, which the harness owns, and the clause is still read from the
  environment: the selector says *which* clause, the environment decides *whether* it
  holds. The same rule covers the values and the harness's own bookkeeping: a fault's
  pre-injection tip, its recordings, the double-injection marker, the submodule path the
  probes bind `{submodule_path}` from, and the post-injection ref snapshot all live in
  `Sandbox.recorded`, which the harness owns. The clone holds nothing under
  `refs/sandbox/` (issue #161, ADR-0021): a ref there holds in every sandbox and in no
  real repository, so a precondition could anchor on it and pass admission.
- `recorded_state_intact` records whether the resolution left the **recorded state**
  alone — today that the work repository was not re-cloned or wiped (every object its refs
  named at the start is still in the store) and upstream's history (`tasks/invariants.py`, checked after the
  fault's own clause passes and recorded on every row it ran for). A row that
  reached the expected state while `recorded_state_intact` is `false` was **spec-gamed**:
  it repaired the fault destructively, satisfying the graded predicate by an
  unintended route. That is its own column in the ablation table and its own
  pooled line in the report, because such a row otherwise carries
  `ground_truth_ok=false` and reads exactly like a resolution that simply failed
  to repair the fault. `null` means the check did not run — an invalid episode, or
  a row written before it existed — and is never counted as gaming. The field was named
  `refs_intact` until issue #96 renamed it; a revision-history row below still uses the old
  name because a record of a time is not rewritten (rule 5).
- **Denominator rule.** `fail`, `fallback` and `refusal` all carry
  their token spend into the means — an episode that crashed after 4,000 tokens
  still cost 4,000 tokens. `invalid` is the sole exception: the episode never
  ran, so it is counted and reported as its own rate but excluded from metric
  denominators. See item 7 below.
- `cached_tokens_in` is separate from `tokens_in` because provider-side prompt
  caching can make the ReAct baseline look cheaper than the work it performed.
  Arm 1's prompts grow with the transcript, so caching flatters it most; the
  confound is recorded so it can be inspected rather than assumed away.
- `model` is recorded per episode because provider-side model drift between
  runs is a confound that silently invalidates a comparison.
- `admission_gate` is the gate the dispatched library's programs passed —
  `two_sided` or `positive_only` — the 2×2's admission factor (ADR-0010).
- `rerank_k` is how many first-stage candidates arm 2's reranker rescored, `null`
  when arm 2 ran single-stage (ADR-0011). With a reranker the threshold judges the
  reranker's score, so a row's `dispatch_score` and `similarity_threshold` are read
  with it.
- `temperature` is the sampling temperature the episode's model calls were sent
  with, read off the completions rather than from run configuration (issue #6).
  The provider sends 0 unless overridden. `null` means no call reported one — a
  replay, which consults no model. It records what was **sent**: whether the
  endpoint honours it has not been checked against a live call, and 0 is not a
  determinism guarantee on a hosted model.
- `dispatch_score` (arm 2) and `admitted` are recorded so a tuned comparison is
  distinguishable from an untuned one.
- The four reason fields are separate because they are four different signals.
  `refusal_reason` holds the guard's reason and is set only when `outcome` is
  `refusal`, so the guard refusal rate is a grouping over that one field and
  cannot pick up anything else. `compile_failure_reason` holds why a compile or
  admission produced no usable program (a malformed reply, a failed gate, a
  program id collision). `invalid_reason` holds why an episode could not be graded at
  all. `replay_failure_reason` holds why a program that *fired* could not be run
  at all — today, a body naming a declared parameter the environment cannot bind,
  so no command executed and there is no postcondition evidence (issue #76); a
  body that ran and failed its postconditions is recorded by the demotion
  instead. A single field carrying all four would silently fold compile failures
  into the safety metric — the defect issue #60 fixed.

### Design

The primary measurement is a **dispatch-level benchmark**, not an episode run:

```
  labelled (repo-state, candidate-program) pairs, split by fault seed
        ├─ admit set    build the precondition vocabulary
        ├─ tune set     calibrate arm 2's representation and threshold
        └─ eval set     the reported numbers
        │
  arm 2 sweeps its threshold; arm 3 is one operating point (ADR-0008)
        │
  mismatch-vs-coverage curve, Wilson intervals, power statement
```

Each pair is labelled by mechanically deriving the expected state from the
fault-injection spec (§3), with ground truth kept in separate code from the
admission postconditions (§6) and validated by two negative controls: a no-op
agent must fail every fault, and a deliberately wrong program must fail too.

A dispatch decision costs no LLM call — arm 3 evaluates predicates, arm 2 scores
text similarity, lexical today and an embedding model behind the same seam
tomorrow — so the pair count is chosen to make the comparison adequately powered
rather than to fit a budget.

**The episode loop is retained only as a demonstration, explicitly underpowered:**

```text
2 measurable faults × 4 occurrences × 3 arms = 24 episodes   (demo, UNDERPOWERED)
    (the nominal 5 faults × 4 × 3 = 60 is not runnable: the three other faults
     return a single fixed sentence and are in EXCLUDED_FROM_BENCHMARK)
```

It is labelled underpowered wherever it appears and excluded from the primary
claim. Its value is showing the harness works end to end, not producing a result.
The 60-episode figure is the nominal grid; the runnable demo is 24, and an
earlier draft stated the nominal figure as though it could run.

Seeds are split into disjoint admit / tune / eval sets and every arm is routed
through the same (fault, seed) pairs, so the comparison is paired rather than
between-populations. The unit of analysis is the **environment** — a resolution
together with the drawn Tier 1 axis values, the instance identity
`FaultSpec.instance_for_seed` names — not the seed and not the episode. An
occurrence is a **variant** the first time its *instance* is seen and a **replay**
only on a genuine repeat of one (ADR-0005; before it the key was the resolution,
because same-resolution seeds built byte-identical environments). The two roles
feed different analyses — the mismatch comparison over the variants, the cost
curve over the replays (see "Figures"). Since ADR-0005 the injectors draw each
state shape's file bodies, local commit count and subjects, and conflict hunk
positions per seed, and `build_sandbox` refuses a draw whose observed resolution
is not the one declared — so a new seed is usually a new environment, and a
mislabelled one cannot enter the comparison. The axes beyond Tier 1 (file names,
submodule paths, branch names) remain issue #6's, because they need probe and body
parameter binding first.

### Figures

**Figure 1 — mismatch vs coverage.** The primary figure. Arm 2's curve over every
distinct acceptance threshold, and arm 3 as a single operating point, since it has
no score to sweep (ADR-0008); mismatch rate against coverage, Wilson intervals at
each operating point, and the pre-registered coverage point — arm 3's own — marked.
Produced by `bench.primary.write_primary_report` (`figure1.csv`, the deliverable, with
every point's numerator, denominator and interval; `primary.txt`; `figure1.png`), one
report per request regime. The report states the matched comparison and the item-3
power statement, unless `vacuous_reason` fires, in which case it states that instead
and draws the curve without a comparison. The #7 dispatching baselines may join the
plane as context (2b as a curve, 2c as a point). The outcomes come from
`bench.library_pairs.library_pair_outcomes`, which builds each pair's sandbox and
dispatches it through the compiled library's own matchers, so the pair-level arms are the
arms the episodes run; ADR-0022 records which pairs it builds.

**Figure 2 — cost vs repeat (secondary).** **Cumulative amortized** tokens and LLM
calls per episode against `occurrence_index`, one line per arm, from the
underpowered demo and **over its replay occurrences only**, with the break-even
marked on the figure and stated in the report text. The accumulation is the
figure's subject, not the per-occurrence mean: compile cost is charged to
occurrence 1, so a compiled arm starts above the baseline and can only cross it
later — or not at all — and a mean per occurrence is a snapshot that cannot show
which. Where no crossing is computable, because the arms share no occurrence index
or because one never crosses, the report says which of those it is rather than
leaving a blank. A variant occurrence is the learning pass — no program admitted
from a state the run had not yet seen can exist — so a curve that included the
variants would average the cost of learning a state into the cost of replaying it.
Arm 1 pays full price on the same occurrence indices, because it has no library,
and that contrast is the comparison the figure exists for. Reported as a cost
model, not as a contribution; the figure and its CSV name the occurrences used.

**Figure 3 — the admission factor.** The 2×2 {dispatch: semantic|precondition} ×
{admission: gated|ungated} comparison, which separates the negative-sandbox
criterion (Claim 3) from predicate dispatch (Claim 2). *Ungated* is the
positive-only gate — every admission check except the negative sandboxes — and
both libraries come from **one compile gated twice** (`build_library(positive_only_root=...)`,
ADR-0010), so they hold the same programs. Each row records its `admission_gate`, and
`bench.report.admission_factorial` gives one cell per (arm, gate); the
{precondition, positive-only} cell is issue #4's arm 3-prime.

### Pre-registered analysis

**Revised 2026-09-13, before any data exists.** The original pre-registration
named an episode-level paired mismatch difference as primary. A method review
found that metric degenerate as designed (ADR-0001). The revision is recorded
rather than silently applied: no episode has been run, so no analysis was chosen
after seeing results.

1. **Primary metric:** the mismatch-versus-coverage curve, and the difference
   between dispatchers **at matched coverage**. The directional claim is stated at
   a pre-registered coverage point; the full curve is reported regardless.
   Defined by ADR-0008 and computed by `bench.coverage`: *coverage* is fires over
   pairs, negatives included; *mismatch* is wrong fires over fires, a fire on a
   negative pair counting as wrong. A fire is wrong when its resolution is not one
   the state **accepts** -- its label, or another resolution its fault's checker
   also passes there (ADR-0023) -- so `rebase` on a `merge`-labelled diverged state
   is not a mismatch, and `discard` on any diverged state with real local work is. Arm 2's threshold is swept over every distinct
   score; arm 3 has no score and is one operating point, and **its coverage is the
   pre-registered coverage point**. Arm 2's point nearest it is the matched one, a
   tie going to the lower coverage, and the coverage gap is reported beside the
   difference. The regimes are compared separately, never pooled (ADR-0004). While
   arm 3 decides every pair correctly — hand-written programs that agree with the
   labelling rules do, by construction — the comparison is vacuous, and the report
   prints `vacuous_reason` instead of it.
2. **Unit of analysis:** the environment -- the instance a seed builds (ADR-0005) --
   not the episode. Seeds split into disjoint admit / tune / eval sets; episodes
   paired by (fault, seed). Within the episode loop the independent observations are
   its **variant** occurrences only: a replay re-asks a state an earlier occurrence
   introduced, and is excluded from every independence claim (see "Ledger"). The plan
   is run as **k = 3 whole-run replicates** (`bench.run.run_replicates`), and
   seed-level uncertainty comes from `bench.report.cluster_bootstrap`, which resamples
   instances with all their arms and replicates, so a repeat never counts as a new
   observation (issue #6, ADR-0012).
3. **Power statement:** required — the detectable effect size at the chosen pair
   count, coverage points, and alpha. `bench.coverage.detectable_difference` computes
   it for two arms' fire counts (two-proportion normal approximation, α = 0.05
   two-sided and power 0.80 by default; ADR-0008 records those as defaults, not as a
   registered α for the directional claim).
4. **Secondary metrics:** tokens and LLM calls per episode by occurrence index,
   accumulated into a running amortized cost with the break-even marked (the cost
   model, Figure 2); **arm 2's embedding currency separately**, never added to the LLM token fields;
   **the arm triple** — success rate, tokens per episode and tokens
   per success, each with its denominator — reported with a **Pareto frontier over the
   three** (`arm_triples.csv`, `pareto.png`), so that cheaper-per-episode, cheaper-per-
   success and more-successful are read together rather than one at a time, per item 8;
   **the issue #7 baselines on that same frontier**, the first of which is the zero-token
   **gold oracle floor** (ADR-0014): it replays the ground-truth variant's hand-written
   resolution, so its success bounds what any arm could reach and its cost bounds the
   cheapest an arm could be, and because it consults ground truth it is an oracle rather
   than a dispatcher and is excluded from the matched-coverage comparison; and **arm
   2c, intent-key dispatch** (ADR-0015), a lookup on the normalised request string that
   abstains when its key's programs disagree -- a dispatcher with no score, so one
   operating point, measurable on the pairs by `bench.coverage.intent_key_outcomes`;
   **arm 2b, a soft vote over arm 3's own probe features** (ADR-0016), whose learned
   threshold is recorded on its rows and whose tie with arm 3 decides item 12; and
   **arm 1b, ReAct with a memory of its own past successes** (ADR-0017), the
   experience-reuse baseline for the cost curve, which runs in the online mode only and
   records how many stored trajectories each episode's prompt carried (`memory_recalled`);
   **the raw character length of each prompt prefix the run sends**, reported once
   rather than per arm because every arm sends the same two prompts — arm 1b's recalled
   memory goes in the user message, not the system prefix — and the arm-level difference
   is how much text accumulates around the prefix, which the input tokens carry; compile success rate; fallback rate; guard refusal rate. The
   episode loop is labelled underpowered and excluded from the primary claim.
5. **Tuning discipline:** arm 2's representation and similarity threshold are
   tuned on the tune set, disjoint from eval, and the value used is written into
   every ledger line. An untuned control arm would be a straw man; a control arm
   tuned on its own evaluation set would be cheating. The record shows which was
   done.
6. **Extension rule:** if the interval on the primary difference spans zero at the
   pre-registered coverage point, extend the pair count rather than re-analysing
   the existing set differently. If it still spans zero, the result is "no
   difference detected at this N", with the interval shown.
7. **Failed episodes stay in the denominator**, with their partial token spend.
   Dropping them would make amortization look better than it is.
8. **Cost per success is reported alongside cost per episode**, because an arm
   that succeeds more often may legitimately spend more per episode.
9. **Invalid episodes are excluded from denominators but never hidden.** An
   episode that could not run (sandbox or infrastructure failure) is recorded as
   `invalid` and reported as a rate. **An invalid rate above 10% makes the run
   suspect**, and it is re-run rather than analysed — infrastructure flakiness
   that removes episodes non-randomly is indistinguishable from a real effect.
10. **"Equal success rate" requires an equivalence test; otherwise the text says
   "comparable".** The words are not interchangeable: failing to detect a difference
   is not evidence of none, and a run this size will usually fail to detect one. The
   report runs a **TOST** on arms 2 and 3's pooled success rates at a
   **pre-registered margin of ±10 proportion points and α = 0.05** — registered here,
   before any data, because a margin chosen after seeing the interval can be widened
   until equivalence passes. It reports the difference, the 90% interval, both
   one-sided p-values, and which of three cases holds: equivalent within the margin;
   outside the margin, so the arms differ by more than it; or too wide to decide,
   which is an underpowered run and **not** a finding that the arms differ. The
   verdict is produced by `bench/report.py` (`success_rate_wording`) rather than left
   to whoever writes the prose, and its variance uses Agresti–Coull-adjusted
   proportions, because the raw Wald variance is zero at a 0%/100% rate and would let
   a single episode's zero-width interval pass as equivalence.
11. **Arm 2 must clear a floor before it counts as the baseline.** Before any eval
   episode, arm 2's strict top-1 is measured on the **informed** regime over the
   **tune** seeds, against the candidate texts of the library the eval dispatches with
   (`bench.similarity_probe.tune_baseline`). Arm 2 is a usable baseline only if the
   **95% Wilson lower bound** of that rate exceeds chance, 1/3 for three candidate
   resolutions (`bench.report.arm2_baseline_floor`). The bound is judged, not the point
   estimate, because one pair above chance is noise; at 24 decidable pairs the floor
   falls between 12 and 13. Below it, a report may not say that precondition dispatch
   beats text similarity. It still reports the comparison, with the floor's verdict
   beside it, because a failed baseline is a result about arm 2 and not a reason to
   drop the row. Registered here, before any data, for the same reason as item 10's
   margin (issue #116, ADR-0007). Figures on the probe's seeds 0–3 and on hand-written
   gold are exploratory and are never judged by this floor.
12. **Claim 2 is restated if a soft vote over the same probes ties arm 3.** Arm 2b
   (issue #7, ADR-0016) scores each admitted program by the fraction of its
   preconditions that hold, the same per-predicate results arm 3 reads, with a
   threshold learned on the **tune** seeds for most correct decisions (ties to the
   stricter floor; `bench.soft_vote.learn_soft_threshold`). On the eval pairs its
   swept curve is matched to arm 3's coverage by item 1's rule, and the two per-fire
   mismatch rates are compared by item 10's TOST at the same ±10pp margin and α.
   **Equivalent** means requiring every probe adds nothing measurable over the same
   information, and Claim 2 is then stated as *"probe-based dispatch beats
   text-similarity dispatch"*. A matched 2b point at threshold 1.0 *is* arm 3 and
   makes its decisions exactly, so that tie is reported as **collapsed** and keeps the
   registered wording (`bench.soft_vote.claim2_verdict`). Registered before any eval
   data.

#### The seed plan and the run invocation

The split is fixed in `bench/splits.py` before any data exists, because a split
chosen after seeing scores is not a split, and the ledger records `seed` on every
row, so a reader must be able to tell which set an episode came from.

```text
smoke  0,1,2,4     4 seeds   shake out the pipeline; admit the programs (the admit set)
tune   1000-1015   16 seeds  calibrate arm 2's similarity threshold (item 5)
eval   2000-2039   40 seeds  the reported numbers
```

**The admit set builds one frozen library** (issue #4, ADR-0009). `bench.build_library`
solves each admit-set `(fault, seed)` against its own empty scratch library -- so nothing
is dispatched while the artifact is built -- compiles and gates the solution with the
same `admit`, and copies every program it produced into one root. The comparison then
runs with `run_benchmark(frozen_library=...)`: every arm dispatches against that root,
nothing is written to it, and every row carries its one `library_hash`. The online mode,
where each arm grows its own library, remains for the cost curve.

Each of those seeds is an *occurrence*, and occurrences split by role on the
**instance identity** (`bench/splits.py`'s `occurrence_roles`, written onto every
ledger row; ADR-0005 decision 5):

| set | seeds | fault | variant occurrences (distinct instances) | replay occurrences |
| --- | --- | --- | --- | --- |
| smoke | 0, 1, 2, 4 | `diverged` | 4 | 0 |
| smoke | 0, 1, 2, 4 | `submodule_moved` | 4 | 0 |
| tune | 1000-1015 | `diverged` | 15 | 1 |
| tune | 1000-1015 | `submodule_moved` | 7 | 9 |
| eval | 2000-2039 | `diverged` | 32 | 8 |
| eval | 2000-2039 | `submodule_moved` | 15 | 25 |

**The independent observations are the distinct instances, and the counts are
measured, not inferred from the grid.** Each measurable fault now draws each state
shape's content per seed along declared Tier 1 axes — file bodies, local commit
count and subjects, and conflict hunk positions — so a set's variant occurrences
are exactly the distinct **instances** its seeds build. The per-resolution
breakdown the report carries (`bench.report.achieved_instances`) is:

| fault | resolution | instances in the eval set |
| --- | --- | ---: |
| `diverged` | `discard` | 18 |
| `diverged` | `merge` | 8 |
| `diverged` | `rebase` | 6 |
| `submodule_moved` | `init` | 5 |
| `submodule_moved` | `remove` | 5 |
| `submodule_moved` | `repin` | 5 |

The 40-seed eval set therefore builds **47 independent environments**, up from 6,
and every resolution clears the owner's target of 4. The counts come from
`FaultSpec.instance_for_seed` over the plan's seeds; reproduce the real-sandbox
measurement, including that distinct identities are distinct environments, with
`.venv/bin/python -m precondition_library.bench.instance_diversity`.

**The episode-level mismatch comparison is still underpowered, for a different
reason.** No interval could be attached at 6 environments. One arm's success
rate now carries a real interval: its 95% Wilson half-width near 0.5 is about
**±18.6pp** at the owner's target of 24 and **±13.7pp** at the 47 achieved. But the
±10pp margin (item 10) is applied to the **difference** between two arms' rates, by
a TOST at a 90% interval, and that interval is wider. With `tost_equivalence` and
both arms at the same observed 50% rate — the most favourable case — the difference's
half-width is about **±22.5pp** at 24 per arm and **±16.5pp** at 47, and ±10pp first
becomes passable at **133 per arm** (87 at an 80% rate, 53 at 90%; any observed
difference needs more). ADR-0006 keeps the margin at ±10pp, so at the achieved N the
expected verdict is "comparable", which the report already produces for an
underpowered run. The pre-registered primary
comparison is unaffected, because it is not computed from the episode loop: it is
the pair-level one over labelled (state, program) pairs (item 1), where the state
grid is crossed with seeds, no library accumulates between pairs, and the pair
count is chosen for power rather than for what a run can pay for (issue #5). The
episode loop's own comparative figure stays reported, labelled underpowered, with
its instance N shown.

**What more episodes would buy.** Replay occurrences for the cost curve, and
increasingly few new instances: the instance count is bounded by the declared draw
space and grows sublinearly with the seed count, so a larger seed set buys mostly
repeats. Independent observations are bought by more *draw space* — the held-out
axes issue #6 still owns (file names, submodule paths, branch names; Tier 2, which
need probe and body parameter binding) — or by the pair-level harness, which
crosses states with seeds and is not budget-bound.

The whole live sequence -- build, 2b tuning, frozen benchmark, admission factorial,
Figure 1 and the online arms -- is one command, `python -m
precondition_library.bench.live --api-key-env DEEPSEEK_API_KEY --out DIR`, which calls the
functions below in this order and writes every artifact under `DIR` (revision 68). Its
caller names the key's source; the package still finds none on its own. A single stage
is invoked like this. The ledger goes outside the repository; the API key
comes from the caller's environment and is never read by this repository
(`provider.py` reads no environment variables and no files):

```python
import os
import tempfile
from pathlib import Path

from precondition_library.bench import run
from precondition_library.bench.ledger import Arm
from precondition_library.bench.splits import TUNE_SEEDS
from precondition_library.provider import DeepSeekProvider
from precondition_library.tasks.registry import ambiguous_intents

provider = DeepSeekProvider(api_key=os.environ["DEEPSEEK_API_KEY"])
run.run_benchmark(
    arms=list(Arm),
    faults=[intent.fault for intent in ambiguous_intents()],
    occurrences=len(TUNE_SEEDS),
    seeds=list(TUNE_SEEDS),
    out=Path(tempfile.gettempdir()) / "precondition-ledger.jsonl",
    model="deepseek-flash",
    provider=provider,
)
```

---

## 8. Failure handling

Rule: **no silent retries, no invisible costs.** Every degradation is attributed
to an arm and recorded with a reason.

| event | action | recorded as |
| --- | --- | --- |
| replay misses postconditions | demote program; fall back to ReAct **for this episode only**; fallback tokens attributed to the arm | `misfired` (derived), with `outcome` showing how the episode then ended |
| a fired body names a declared parameter this environment cannot bind | no command runs; demote the program; fall back to ReAct **for this episode only** | `replay_failure_reason`, with `outcome` showing how the episode then ended (issue #76) |
| same program mismatches twice | withdraw from dispatch; retain for analysis | `quarantined` |
| compile fails admission | stored as a `candidate` and its rejection reason recorded, not discarded; episode keeps its token cost | `candidate`, `admitted=false`, `compile_failure_reason` |
| guard refuses the body | no execution; fall back to ReAct | `refusal` + `refusal_reason` |
| replay exceeds timeout | process killed, sandbox destroyed | `fail`, `timed_out` |
| no program applies | solve with LLM, compile, admit | `fallback` (expected, not a failure) |
| provider error / rate limit / transport failure (timeout, dropped connection) | capped backoff retry (429, 5xx and transport failures; never another 4xx or a malformed body) | `fail`, partial token spend retained, every attempt counted in `llm_calls` |
| sandbox build fails | episode invalidated, counted | `invalid` + `invalid_reason` |

A fallback is a **cost, not a non-event**: every time no program applies, the arm
pays full price. The cost curve is therefore partly a coverage story, which is
why `fallback` ("no program for this state") and `mismatch` ("a program claimed
there was one, wrongly") are distinct outcomes.

---

## 9. Safety and prompt injection

The compile step reads repository content — commit messages, file contents,
branch names, submodule URLs — all of which an attacker controls, and then
authors code that **runs unattended on later episodes**. This is a real
vulnerability, not a theoretical one, and it is designed against rather than
noted.

| threat | mitigation |
| --- | --- |
| Injected instructions in repo content steer the model while compiling | repo-derived text is passed in a delimited untrusted channel with explicit framing that it is data, never instruction |
| The compile step executes something while "testing" | the compile step **never executes** generated code; execution belongs to `runtime`, on a throwaway sandbox, behind the guard |
| Generated body exfiltrates repository contents | guard refuses outbound network calls and reads of credentials/SSH keys/env vars |
| Generated body writes outside its environment | guard refuses paths outside `env_root`; `HOME` is redirected into the sandbox and the environment is reduced to an allowlist (`PATH`, locale, `TMPDIR`, plus the pinned `GIT_*` variables), so an API key exported by the operator cannot reach the body |
| Generated body force-pushes to a shared remote | guard refuses pushes to any remote not recognised as a sandbox |
| Generated body undoes the git hardening per invocation -- `git -c core.hooksPath=<dir the attacker committed>` runs that directory's hooks, because command-line config wins over the pinned environment (verified, issue #159) | the guard refuses every per-invocation config override (`-c`, `--config-env`) outside an **allowlist** of one -- `protocol.file.allow=always`, which the submodule family needs -- and any body that sets `GIT_CONFIG_*` in its own environment; the ReAct `run_git` tool applies the same parser (`sandbox.disallowed_git_config_overrides`), and the injection suite measures the tier. A persistent repository `git config` write needs no refusal: the environment's `GIT_CONFIG_COUNT` outranks repository config |
| Generated body is destructive *inside* the sandbox | **accepted** — that is what the sandbox is for; the sandbox is destroyed afterwards |
| A generated precondition or postcondition **changes** the state it is observing | probes are screened by the same guard as bodies, and every probe runs between two snapshots of the sandbox (`runtime.probes.sandbox_state`: working-tree files, index, `.git/config`, HEAD, and every ref of the clone and the upstream). A probe that changed any of them is refused, reported as not holding with `refused` set, and admission rejects a program whose precondition is refused rather than reading the refusal as a "no" (issue #10). Not covered: other files under `.git` (objects a probe adds are unreferenced; hooks are disabled by `core.hooksPath`), and anything outside the sandbox, which is the guard's job |

**Structural protections, not just screening:**

- Phase 1 never points a replay at a real repository. Admission, benchmarking,
  and replay all run on disposable sandboxes.
- The replay timeout bounds damage from a hung or looping body, and it bounds the
  **whole process group**: every body and probe runs in its own group (a new session
  on POSIX, a new process group on Windows), and on expiry the group is killed, so
  work a body put in the background cannot outlive it (`runtime.confine`, issue #10).
  On POSIX the command also runs with a per-file size limit (256 MiB) and core dumps
  off.
- `runtime/replay.py` cannot reach `provider` (enforced by test), so a replay
  cannot be talked into asking for help.
- A program may carry **argv-template `steps`** instead of a shell `body`
  (`runtime.templates`, issue #10): a closed catalogue of git operations the task
  family needs, each built into an **argv array** from the sandbox's bound values
  and the step's literals and run with no shell — so an attacker-controlled value
  (a commit message, a `.gitmodules` path) is one element git receives verbatim
  and cannot become code. Bound values are validated before they reach argv (refs
  against a charset, paths against a charset and realpath containment under the
  working tree), and the catalogue has no entry for the network, a force-push, or
  a write outside the tree. This is the positive boundary the free-form body
  lacks; the gold resolutions run through it. The model-compiled online arms still
  emit shell bodies behind the guard — migrating the compile step to emit `steps`
  is issue #4's territory and not done here.
- An adversarial injection suite (`bench.injection`, issue #10) drives the worst
  case these defences exist for: a program whose body or probe is attacker text
  verbatim, planted through each of the four origins above (commit message,
  filename, branch name, issue text), as if the compile step were fully steered.
  It reports containment per tier against planted canaries — a file outside the
  sandbox, a planted secret, a git hook, a backgrounded writer — and the network
  and force-push tiers, which cannot run without real egress or a real remote,
  are scored by the guard's refusal. The compile-time untrusted-channel tier
  needs a model and is reported as *not measured* rather than omitted. It does
  not run a model or touch a real repository.
- Each body and probe runs with **no network, where the host allows it**
  (`runtime.confine`, issue #10): a fresh, empty network namespace via
  `unshare --net`, a kernel boundary rather than the guard's textual screen. The
  sandbox's only remote is a local filesystem path, which needs no network, so
  isolation does not change a replay's result. The privilege to create a
  namespace may be withheld (a non-root runner, a locked-down container); then the
  command runs without it and `ReplayResult.network_isolated` records that it did —
  the owner's choice to run and record, not refuse. Linux only.

**Residual risk, accepted and documented:** a generated body may perform
destructive-but-permitted actions within its sandbox. Network isolation is
kernel-enforced where the host can create a network namespace (`unshare --net`,
above) and falls back — recorded as not isolated — to the textual and
environmental screen where it cannot: the guard refuses recognisable network
tools and URLs in the body, and the environment allowlist with a redirected
`HOME` keeps ambient credentials out, but neither stops an endpoint assembled at
run time (the guard's "What the guard cannot see") once the namespace is
unavailable. A separate unprivileged user and a real disk quota still need
privilege a process cannot give itself, so they are a **runner requirement** the
execution container must provide (ADR-0013, `docs/running-unattended.md`) rather
than library code; the library records whether the network namespace applied but
does not verify the user or the quota. A body that calls `setsid` leaves its process group and escapes the
group kill, and Windows gets the group kill but neither the resource limits nor
the network namespace. Running compiled programs against real repositories
requires human review of each program and is explicitly out of scope; the guard
is a seatbelt, not a sandbox boundary.

---

## 10. Testing strategy

```
GOLD FIRST      hand-written solutions must satisfy the fault checkers before
                any agent runs. A broken checker produces plausible numbers
                that mean nothing. INTENDED to be enforced by tests/ before
                anything else; NOT yet implemented -- test_checkers_against_gold
                is skipped until phase 1. Gold resolutions now exist for the two
                ambiguous intents (bench/gold/), but no checker has run against
                them.
DETERMINISM     same seed -> byte-identical faulted environment; the regression
                that would show up as variance between arms. Different seeds
                -> different instances when they draw different Tier 1 axis
                values, and the same instance only on a genuine repeat: measured
                over the 60 pre-registration seeds after ADR-0005, distinct
                `instance_for_seed` identities build distinct environments (issue
                #86), and `build_sandbox` refuses a draw whose observed resolution
                is not the declared one. Before ADR-0005, seeds selecting one
                resolution were byte-identical, commit SHAs included; they are not
                any more.
TEXT CONTROL    a bag-of-words classifier trained on the request text alone
                reports the informed/uninformed split. The uninformed regime
                cannot carry the resolution by construction (the sampler never
                consults state, so the AUC is 0.500 for any classifier and any
                phrasing list); LEAKAGE_CEILING gates it as a plumbing tripwire
                for state reaching the sampler, not as a leak detector, so it
                cannot certify the phrasing distribution. The wording is therefore
                checked directly instead: `test_no_phrasing_names_a_resolution`
                rejects any whole-word variant id in either channel, which is the
                literal leak the AUCs cannot see. A revealing paraphrase remains a
                review obligation. The informed regime
                is a genuine measurement: 0.962 / 0.945 -- the boundary
                condition where the wording nearly determines the resolution
                and the mechanism is not needed. Pinned by a positive control
                that fires on an intent whose informed wording fully determines
                the answer, so the control cannot pass by being a no-op. Only
                registered intents are measured; the three unconverted faults
                return a fixed sentence and are excluded (`EXCLUDED_FROM_BENCHMARK`).
IMPORT GRAPH    replay cannot reach provider, directly or transitively.
                IMPLEMENTED AND PASSING (tests/test_replay_isolated_from_provider.py)
ZERO TOKEN      stronger than the import test: replay runs with a provider whose
                complete() RAISES. Any hidden call path fails loudly at the
                integration level, where the import test only sees statically.
GUARD TABLE     bodies that must be refused, one line each to extend.
LEDGER INTEGRITY  every episode writes exactly one record; denominators must be
                reconstructable from the ledger alone.
NO SILENT SKIP  a skipped test must carry the issue that implements it. A test
                suite that quietly skips is a suite that passes for the wrong
                reason.
DECLARED STATE  every stub and every skipped test is declared in
                tests/test_declared_state.py and the declaration is asserted
                against the code, so implementing a stub or un-skipping a test
                fails CI until the declaration -- and the prose that restated it --
                moves too. A small claims table pins the status sentences that
                reduce to a mechanical fact, each failing with the document to
                update. It cannot detect a document contradicting another document,
                or one whose meaning contradicts the code; that stays a review
                obligation (CONTRIBUTING rule 5).
```

The zero-token test is the one that matters most **for the cost model**: the
replay invariant is what keeps the reported token totals honest, and the most
likely way to make them silently false is an import nobody noticed. Both a static
test and a runtime test guard it. It protects the cost model, not the primary
claim.

---

## 11. Phases

| phase | contents | exit criterion |
| --- | --- | --- |
| 0 | design, scaffold, invariants, CI | **done** — this document, committed skeleton |
| 1 | reframe after review; correct the experimental design (issues #3, #4, #9) | task text no longer labels the fault; arms share one frozen library and an identical admission gate; ground truth is decoupled from the artifact contract |
| 2 | dispatch-level benchmark harness, calibration sweep, power statement (#5, #6) | labelled (repo-state, candidate-program) pairs exist; arm 2 sweeps a threshold and arm 3 is one operating point (ADR-0008); a power statement is written |
| 3 | baselines that make the control arm credible (#7); safety hardening (#10) | the probe-classifier, intent-key, reflexion, and gold-script baselines run; the injection suite reports containment per defence tier |
| 4 | run the benchmark; publish the mismatch-vs-coverage curves | Figure 1 exists with Wilson intervals at each coverage point |
| 5 | episode loop as a demo, explicitly underpowered | the harness runs end to end; labelled underpowered wherever reported |
| 6 (optional) | DSH plugin wrapper around the admitted library | out of scope unless phases 1–5 land |

---

## 12. Decisions and rejected alternatives

| decision | choice | rejected alternative and why |
| --- | --- | --- |
| axis of contribution | the matched-coverage measurement (Claim 2), with the negative-sandbox admission criterion as a second candidate | **a novel architecture** — dropped (ADR-0001): compile-once replay is established prior art (PreAct, SkillDroid, Auto) and precondition dispatch is MACROPS, 1972 |
| headline claim | none — the project reports a measurement, not a claimed architecture | **compile-once, replay-without-model** — dropped as prior art, ADR-0001 |
| baseline | a ReAct-style observe/act/observe loop (Yao et al., ICLR 2023), given the same tools and sandbox | self-modifying agent — generations are serial and each needs a full evaluation sweep, so a short project sees too few generations to distinguish signal from noise |
| | | swarm of tiny agents — cheap per run but high variance, and a positive result is hard to attribute to any mechanism |
| | | memory-as-program — a real problem, but it needs long-horizon tasks that are themselves expensive to run |
| comparison | three arms (react / semantic / precondition) | two arms (react vs precondition) — cheaper, but then Claim 2 has no control and a reviewer is right to say semantic dispatch was never given a fair shot |
| dispatch mechanism | executable preconditions | text-similarity-only, lexical today with an embedding model behind the same seam as the intended replacement — it sees the state as words but cannot evaluate it, and is *hypothesized* to mis-fire on structurally different environments that read alike; testing that hypothesis is what the benchmark is for |
| | | one monolithic growing program with a dispatcher — the most striking demo, but it rots, and it cannot ablate *which* mechanism helped |
| **arm 2's baseline and seam (2026-09-20, ADR-0003; regime correction 2026-09-21 in revision 36, ADR-0004 — proposed)** | the shipped lexical scorer stays, and its baseline is quoted **per intent within the informed request regime** over the whole ambiguous subset, with strict top-1 operative and the AUC beside it — hand-written gold on the probe's seeds 0–3, **not** the pre-registered split; the uninformed regime is chance by construction and is reported beside it as a plumbing tripwire, never as baseline | **IDF/BM25 weighting** — measured on the informed regime: it raises the AUC (0.6380 Jaccard, 0.6658 cosine, against 0.6172) while *lowering* strict top-1 (13/24 and 13/24 against 15/24), and document frequencies need a corpus the one-method seam has nowhere to carry; **dropping the constant `intent` from `_program_text`** — rejected in ADR-0003, which records the then-pooled measurement; it would invalidate comparability with the recorded figures for no measured gain, and nothing in the regime correction revives it; **quoting one intent's figure as the family's** — within the informed regime the two ambiguous intents differ by more than 0.2 AUC (0.8125 against 0.6007), so neither describes the family; **pooling the informed and uninformed regimes** — measured: the pooled figure (0.5340 and 23/48) averages a channel where the wording nearly gives the answer away with one that is chance by construction and describes neither, so the probe now refuses to produce it (ADR-0004) |
| domain | branchy git maintenance chores | synthetic benchmark suite — cleanest ablation, but produces an agent nobody uses and leaves "does this matter" unanswered; chores were chosen because correctness is free to check and the recurrence is real |
| stack | standalone Python engine, own the loop | DSH plugin (TypeScript) — cannot ablate a loop the host owns; measuring loop cost from inside a tool is not possible |
| sandbox | disposable repos only | real forks — replayed programs execute unattended; real repositories are not an acceptable target for unreviewed generated code |
| benchmark episodes | manufactured by seeded fault injection | waiting for real faults to recur — 60 recurrences will not occur in three weeks, so the experiment could not reach N |
| **reframe after review (2026-09-13, ADR-0001)** | re-center on the open measurement: the dispatch comparison becomes the spine, the agent becomes its harness, Claim 1 is dropped as a contribution | **keep the agent central and merely rewrite the prose** — preserves the original vision, but the headline becomes "a modern instance of a classical mechanism" and invites "MACROPS for git chores"; the measurement is the only thing here that is actually open |
| | | **abandon the project** — the narrow gap is real and unmeasured and the engineering is already scaffolded; abandonment would be a reaction to losing a claim, not to losing the question |
| primary metric location | dispatch-level benchmark at matched coverage | episode-level paired mismatch difference — degenerate as designed: one fixed task sentence per fault made the task text the ground-truth label, so the control arm could not mis-fire by construction |
| unit of analysis (2026-09-27, ADR-0005) | the **environment** — a resolution plus its drawn Tier 1 axis values, the `instance_for_seed` identity — with a variant occurrence the first sight of each instance | treating each episode as an independent sample — pseudo-replication that inflates N and leaks the admitted instance into evaluation; and keying on the resolution (the rule before ADR-0005), which counted one environment many times because same-resolution seeds were byte-identical |
| citation policy | every citation checked against the source by the author before publication — a hygiene pass, not independent review | trusting a research agent's prior-art sweep — it produced five wrong attributions and one false negative claim about a repository in the author's own ecosystem |

### Open risks

1. **Arm 2 may saturate, or may be too weak to rank at all.** The arm scores
   lexical overlap today, so its ceiling is surface form; whether that ceiling is
   too low to rank the library is for the tune set to show, and a control arm
   that scores almost nothing would flatter preconditions. A real embedding model
   behind the same seam is the intended replacement, and a strong one may make
   similarity dispatch nearly as good as preconditions on five well-separated
   faults. If so, Claim 2 dies — and the design should add faults that are
   *phrased alike but structurally different*, which is where embeddings should
   fail and probes should not. Watch for this in phase 2, before the full run.

   The discrimination probe gives an exploratory reading of this risk before any
   episode runs (ADR-0003, narrowed by ADR-0004; gold programs, the declared
   state grid, seeds 0–3 — the probe is **not** the pre-registered plan, and
   these are not tune-set figures; re-measured per request regime in revision
   36). On the **informed** channel, where the wording nearly gives the
   resolution away, the shipped scorer scores **AUC 0.6172, strict top-1 15/24
   (63%)** against a 33% chance for three candidates, and that baseline hides the
   spread that is the risk made concrete — **0.8125 / 67%** on
   `restore_submodule_state` against **0.6007 / 58%** on
   `sync_fork_with_upstream`. The arm is above chance on both, so the lexical
   proxy is a competent baseline rather than a straw man and a win for
   precondition dispatch has to be won against it. The **uninformed** channel is
   chance by construction (**AUC 0.5000, strict top-1 8/24, 33%**) and is the
   plumbing tripwire, not baseline material: the 8 negative pairs belong to it,
   and a rise there would mean state had begun reaching the sampler. This is why
   ADR-0003 requires the per-intent breakdown beside any pooled figure, why
   ADR-0004 makes the informed regime the baseline and forbids pooling the two
   channels, and why the embedding swap stays open as the one remaining
   candidate: filling the seam would change the mechanism rather than the
   weighting, and on the informed regime the embedding does not improve on the
   lexical top-1 (**12/24** against **15/24**), so nothing measured so far does.
2. **Compile cost may dominate.** If compiling costs as much as several ReAct
   episodes, amortization needs many recurrences. The crossover point is the
   honest result — but it should be checked early, since it determines whether
   three occurrences is enough structure.
3. **Fault leakage.** Injected faults may leave detectable artifacts (a
   suspiciously named branch, a telltale commit message) that make recognition
   artificially easy. Two halves, and only one is checked: the *wording* half is
   gated by `test_no_phrasing_names_a_resolution`, while the *injected artifact*
   half needs a repo to inspect and so waits on the live sandbox (issue #4).
4. **Five faults may be too few** for a mismatch comparison with usable
   intervals. The extension rule in §7 covers it, at the cost of episodes.
5. **Model drift.** Provider-side model updates mid-experiment would confound
   everything. `model` is recorded per episode; a version change invalidates the
   affected run and requires re-running that arm.
6. **Three of the five faults are not converted.** `dirty_tree`,
   `branch_renamed`, and `lockfile_conflict` still return a single fixed request
   sentence, so for them the text remains a perfect class label — the original
   defect. They are scoped out of this change and **must not be included in any
   dispatch measurement** until they gain an `IntentSpec` with two or more
   state-decided resolutions. Enforced rather than
   merely stated: `EXCLUDED_FROM_BENCHMARK` in `tasks/registry.py` names them, and
   a test asserts every fault is either intent-covered or listed there, so a fault
   cannot be silently absent from both.

---

## 13. Prior work and positioning

Filled in 2026-09-13. **Every citation below was checked against the source by the
author** — title, authors, venue, and each attributed figure — after the sweep that
produced them was found to contain five wrong attributions and one false negative
claim about a repository in the author's own ecosystem. Nothing enters this
section, or the README, unchecked. The full table, with per-work caveats, is in
the README.

**This is not independent review.** The check was performed by the same author, so
treat it as a hygiene pass rather than external validation.

### What prior art settles

Compile-once replay is established, not novel. PreAct (arXiv:2606.17929) compiles
a computer-use trace into a state machine with per-state verification predicates
and parameter lifting, replaying 8.5-13× faster with no per-step LLM calls, and
documents a `cov=100%/score=0` "lossy replay" failure. SkillDroid
(arXiv:2604.14872) compiles GUI trajectories into parameterized templates and
replays with zero LLM calls. Auto (arXiv:2607.04542) compiles
witnessed-deterministic spans into signed artifacts gated on differential replay,
reporting 2,775 vs 17,692 µ$ over 300 items and 48.9% silently wrong under a loose
guard. LATM (arXiv:2305.17126, ICLR 2024) builds a reusable tool from
demonstrations, then has a cheaper model invoke it — note that its replay phase
still calls an LLM, so it evidences *cheaper* replay, not free replay.

Executable-precondition dispatch is classical, not novel. MACROPS (Fikes, Hart &
Nilsson, *Artificial Intelligence* 3(4):251-288, **1972**) dispatches a cached
generalized plan by testing precondition kernels against live state, with an
explicit replan fallback; 1971 is the separate STRIPS paper. Soar chunking (Laird,
Rosenbloom & Newell, *Machine Learning* 1(1):11-46, 1986) caches compiled rules
re-fired on matching conditions. Options (Sutton, Precup & Singh, *Artificial
Intelligence* 112(1-2):181-211, 1999) give an option's initiation set the role a
precondition plays for a policy — an analogy, not an identity, since an option
also carries a termination condition that this project's preconditions lack.
Adaptation-guided retrieval (Smyth & Keane, *Artificial Intelligence*
102(2):249-293, 1998) argues it is often unwarranted to assume that the most
similar case is also the most appropriate for reuse.

### What brackets the open question without settling it

A deployed deterministic executability gate (arXiv:2608.01050) removes 59.4% of
matched skill-message pairs and 59.1% of skill-description tokens, with 90.5%
context reduction, and its gate-removed counterfactual selected a skill blocked as
non-executable in 7.8% of conversations. But it is a cascade *after* semantic
recall — it can only prune, never rescue a recall miss — it covers ten skills in
one domain family, and no head-to-head comparison is reported.

A retrieval-risk benchmark (arXiv:2606.10388v2) measures top-K exposure of harmful
sibling skills at HSR@3 0.346-0.372 for public retrievers versus 0.007 for a
controlled resolver. That is retrieval *exposure*, not wrong-program *execution*,
and again no precedence-versus-similarity dispatch comparison. These figures
belong to v2 under its v2 benchmark name; the earlier title has different, much
smaller figures.

### The hypothesis that survives

**The hypothesis:** at matched dispatch coverage, executable-precondition dispatch
will mis-fire less often than text-similarity dispatch, where mismatch is scored as
an outcome orthogonal to episode success. The mechanism is 1972; **that comparison
has not been measured.** Running it is the intended contribution, and no result
exists yet — this section describes a hypothesis and an intended output, not a
finding.

The negative-sandbox admission criterion (§6) is the secondary candidate: a
requirement that no confirmed work publishes, with the closest published gate
being exit-condition-based and applied as a cascade after semantic recall — a
different test. Its cheapness and enforceability are design intentions, not
findings.

---

## 14. Interaction with the operator-supplied prompt

A system prompt and tool surface for the agent will be supplied separately and
is expected to change during development. The design isolates it:

```
agents/react.py    system prompt + tool schemas   <- swappable
agents/compile.py  compile prompt                 <- swappable
        ────────────────────────────────────────
        dispatch, admission, runtime, ledger      <- NOT swappable per-arm
```

Changing the prompt must never change what the experiment measures. If a change
to the prompt alters arms 2 and 3 differently, it has stopped being a prompt
change and become an architecture change, and must be recorded as such.
