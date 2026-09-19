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
baseline — with cost per success reported alongside cost per episode (§7), since
an arm that succeeds more often may legitimately spend more. This is an
engineering assumption and a cost model. It is established prior art and is never
presented as a finding.

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
  model: deepseek-chat
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
                                 has nothing to do with.
             sibling resolution  the program's own fault, injected at a seed whose
                                 state a *different* resolution of the same intent
                                 is correct in. A program for one resolution must
                                 not fire where a sibling is the right answer.

           Each rejection names the class that rejected it and the number of
           states that class checked, so a reader can tell how much of the gate
           actually ran. A program that accepts any of these fires where firing is
           wrong, which is exactly the mismatch failure this project measures.
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
 tokens_in, tokens_out, cached_tokens_in, llm_calls, wall_clock_s,
 outcome: success|fail|fallback|refusal|invalid, timed_out,
 correct_variant, fired_variant, ground_truth_ok, refs_intact,
 program_id, dispatch_score, admitted,
 refusal_reason, compile_failure_reason, invalid_reason, replay_failure_reason, model}
```

- `occurrence_index` — 1 for the first time this fault type is seen, 2 for the
  second, and so on. Grouping by it produces the headline curve.
- `occurrence_role` — `variant` for the first occurrence of a resolution of this
  fault, `replay` for every later one. Declared by `bench/splits.py` from the
  injector's own seed-to-resolution mapping and written onto every row by
  `bench/run.py`; required, with no default. **The two analyses need different
  occurrences.** The cost curve is only meaningful on the replays, because a
  variant is the first sight of a state and no program can have been admitted
  from it yet — the curve bends exactly where a state recurs. The mismatch
  comparison is only meaningful on the variants, because a replay's state was
  introduced by an earlier occurrence and the program that answers it was
  admitted there, so counting a replay counts one observation twice. It records
  the plan's role and not what happened: a row labelled `replay` may still have
  paid full price, because no program was admitted for its state or the one that
  fired was refused. `llm_calls`, `outcome` and `fired_variant` say what
  happened. A reader who does not know this will compute the curve over the
  occurrences where it cannot bend, or an interval over one observation counted
  many times.
- **Correctness is derived, not stored.** `correct_variant` is the ground truth for
  the state (from the intent's decision rules, in separate code from the programs'
  probe strings), `fired_variant` is what the program that ran actually resolves,
  and `ground_truth_ok` is whether the environment reached the expected state.
  `misfired` and `succeeded` are computed from those, so the quadrant that matters —
  a wrong fire in an episode that nevertheless succeeded via the fallback — is
  expressible. A stored outcome could not hold both halves without the two
  disagreeing, and `outcome` therefore records only how the mechanism completed.
- **Spec-gaming is derived from a fact, like the other correctness verdicts.**
  `refs_intact` records whether the resolution left the recorded `refs/sandbox/*`
  state and upstream's history alone (`tasks/invariants.py`, checked after the
  fault's own clause passes and recorded on every row it ran for). A row that
  reached the expected state while `refs_intact` is `false` was **spec-gamed**:
  it repaired the fault destructively, satisfying the graded predicate by an
  unintended route. That is its own column in the ablation table and its own
  pooled line in the report, because such a row otherwise carries
  `ground_truth_ok=false` and reads exactly like a resolution that simply failed
  to repair the fault. `null` means the check did not run — an invalid episode, or
  a row written before it existed — and is never counted as gaming.
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
  both dispatchers sweep their acceptance threshold
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
between-populations. The unit of analysis is the fault seed, not the episode:
occurrences 2-4 were to be **held-out variants** of a fault (different branch
names, file sets, conflict positions, submodule states), or relabelled
"replays" and excluded from independence claims. **The replay branch is the one
this design takes, because the injectors do not vary those things by seed** (see
the revision history, row 13, and issue #6, which owns widening them): a fault's
`INJECTED_STATES` declares three states and everything else about the injected
environment is fixed, so an occurrence whose resolution has already been seen is
a repeat of that state rather than a held-out instance of it. So an occurrence is
a **variant** the first time its resolution is seen and a **replay** every later
time, and the two are used by different analyses — the mismatch comparison over
the variants, the cost curve over the replays (see "Figures").

### Figures

**Figure 1 — mismatch vs coverage.** The primary figure. Both dispatchers swept
across acceptance thresholds; mismatch rate against coverage, Wilson intervals at
each operating point, and the pre-registered coverage point marked.

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
criterion (Claim 3) from predicate dispatch (Claim 2).

### Pre-registered analysis

**Revised 2026-09-13, before any data exists.** The original pre-registration
named an episode-level paired mismatch difference as primary. A method review
found that metric degenerate as designed (ADR-0001). The revision is recorded
rather than silently applied: no episode has been run, so no analysis was chosen
after seeing results.

1. **Primary metric:** the mismatch-versus-coverage curve, and the difference
   between dispatchers **at matched coverage**. The directional claim is stated at
   a pre-registered coverage point; the full curve is reported regardless.
2. **Unit of analysis:** the fault seed/family, not the episode. Seeds split into
   disjoint admit / tune / eval sets; episodes paired by (fault, seed). Within the
   episode loop the independent observations are its **variant** occurrences only:
   a replay re-asks a state an earlier occurrence introduced, and is excluded from
   every independence claim (see "Ledger").
3. **Power statement:** required — the detectable effect size at the chosen pair
   count, coverage points, and alpha.
4. **Secondary metrics:** tokens and LLM calls per episode by occurrence index,
   accumulated into a running amortized cost with the break-even marked (the cost
   model, Figure 2); **the arm triple** — success rate, tokens per episode and tokens
   per success, each with its denominator — reported with a **Pareto frontier over the
   three** (`arm_triples.csv`, `pareto.png`), so that cheaper-per-episode, cheaper-per-
   success and more-successful are read together rather than one at a time, per item 8;
   compile success rate; fallback rate; guard refusal rate. The episode loop is labelled
   underpowered and excluded from the primary claim.
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

#### The seed plan and the run invocation

The split is fixed in `bench/splits.py` before any data exists, because a split
chosen after seeing scores is not a split, and the ledger records `seed` on every
row, so a reader must be able to tell which set an episode came from.

```text
smoke  0,1,2,4     4 seeds   shake out the pipeline; admit the programs (the admit set)
tune   1000-1015   16 seeds  calibrate arm 2's similarity threshold (item 5)
eval   2000-2039   40 seeds  the reported numbers
```

Each of those seeds is an *occurrence*, and occurrences split by role
(`bench/splits.py`'s `occurrence_roles`, written onto every ledger row):

| set | seeds | variant occurrences per family | replay occurrences per family |
| --- | --- | --- | --- |
| smoke | 0, 1, 2, 4 | 3 | 1 |
| tune | 1000-1015 | 3 | 13 |
| eval | 2000-2039 | 3 | 37 |

**Three, not forty, is the number the independent observations come to**, and it
is the injector grid that fixes it. Only the two fault families with an ambiguous
intent are measurable (`registry.ambiguous_intents()`); the other three are
excluded from any dispatch measurement, named in `EXCLUDED_FROM_BENCHMARK`. Each
measurable fault's injector declares exactly three states, and a program is
admitted for the resolution of one of them, so a seed set of any length yields at
most three variant occurrences per family — six episodes across the two families.
Everything after the first sight of a state is a replay: a real repeat of the
run's own earlier state, which is what the cost curve is read from and what no
independence claim may be read from. **A larger seed set does not change the
count**; it buys replay occurrences, not power.

**The eval set is therefore not merely underpowered for the episode-level
mismatch comparison — the episode loop cannot support it at any seed count.** The
previous statement here said eighty decisions could not put a usable Wilson
interval around a mismatch difference; the honest arithmetic is that only six of
those eighty are independent observations, and an interval over six is wider
still. The pre-registered primary comparison is unaffected, because
it is not computed from the episode loop: it is the pair-level one over labelled
(state, program) pairs (item 1), where the state grid is crossed with seeds, no
library accumulates between pairs, and the pair count is chosen for power rather
than for what a run can pay for (issue #5). The episode loop's own comparative
figure stays reported, labelled underpowered, with its variant N shown.

**What more episodes would buy.** Replay occurrences for the cost curve, and
only that: the 40-seed eval set is sized for a repeat structure long enough to
show whether a compiled arm's cost falls and the baseline's does not, not for the
comparison. Independent observations are bought by **more states**, not more
seeds — the injector work issue #6 owns (held-out variants with new branch names,
file sets, conflict positions, submodule states) — or by the pair-level harness,
which crosses states with seeds and is not budget-bound.

A run is invoked like this. The ledger goes outside the repository; the API key
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
    model="deepseek-chat",
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
| provider error / rate limit | capped backoff retry | `fail`, partial token spend retained |
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
| Generated body is destructive *inside* the sandbox | **accepted** — that is what the sandbox is for; the sandbox is destroyed afterwards |

**Structural protections, not just screening:**

- Phase 1 never points a replay at a real repository. Admission, benchmarking,
  and replay all run on disposable sandboxes.
- The replay timeout bounds damage from a hung or looping body.
- `runtime/replay.py` cannot reach `provider` (enforced by test), so a replay
  cannot be talked into asking for help.

**Residual risk, accepted and documented:** a generated body may perform
destructive-but-permitted actions within its sandbox, and network isolation is
not kernel-enforced. It is textual and environmental: the guard refuses
recognisable network tools and URLs in the body, and the environment allowlist
with a redirected `HOME` keeps ambient credentials out, but neither stops an
endpoint assembled at run time (the guard's "What the guard cannot see"). There
is no `sandbox-exec` here; kernel-enforced isolation is issue #10's territory
and is not implemented. Running compiled programs against real repositories
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
DETERMINISM     same seed -> byte-identical faulted environment; different
                seeds -> genuinely different instances. Non-determinism would
                appear as variance between arms.
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
| 2 | dispatch-level benchmark harness, calibration sweep, power statement (#5, #6) | labelled (repo-state, candidate-program) pairs exist; both dispatchers sweep a threshold; a power statement is written |
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
| domain | branchy git maintenance chores | synthetic benchmark suite — cleanest ablation, but produces an agent nobody uses and leaves "does this matter" unanswered; chores were chosen because correctness is free to check and the recurrence is real |
| stack | standalone Python engine, own the loop | DSH plugin (TypeScript) — cannot ablate a loop the host owns; measuring loop cost from inside a tool is not possible |
| sandbox | disposable repos only | real forks — replayed programs execute unattended; real repositories are not an acceptable target for unreviewed generated code |
| benchmark episodes | manufactured by seeded fault injection | waiting for real faults to recur — 60 recurrences will not occur in three weeks, so the experiment could not reach N |
| **reframe after review (2026-09-13, ADR-0001)** | re-center on the open measurement: the dispatch comparison becomes the spine, the agent becomes its harness, Claim 1 is dropped as a contribution | **keep the agent central and merely rewrite the prose** — preserves the original vision, but the headline becomes "a modern instance of a classical mechanism" and invites "MACROPS for git chores"; the measurement is the only thing here that is actually open |
| | | **abandon the project** — the narrow gap is real and unmeasured and the engineering is already scaffolded; abandonment would be a reaction to losing a claim, not to losing the question |
| primary metric location | dispatch-level benchmark at matched coverage | episode-level paired mismatch difference — degenerate as designed: one fixed task sentence per fault made the task text the ground-truth label, so the control arm could not mis-fire by construction |
| unit of analysis | the fault seed/family, with held-out variant occurrences | treating each episode as an independent sample — pseudo-replication that inflates N and leaks the admitted instance into evaluation |
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
