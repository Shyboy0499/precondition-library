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
embedding dispatch — a mis-fire being a program that runs, claims success, and did
not — with mismatch logged independently of episode success. The mechanism is
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
ground-truth label, so embedding dispatch could not mis-fire by construction.
Analysing it would have produced a number that looked like a result while
measuring nothing.

### What would falsify this

- **No difference at any coverage.** Then the finding is that executable
  preconditions buy no dispatch accuracy over embeddings in this domain, and the
  negative-sandbox admission factor (Claim 3) becomes the contribution.
- **The injected faults leak a marker.** If faults are recognisable from the task
  text, semantic dispatch wins for the wrong reason. No cross-fault
  recognisability check exists yet: the text control in `bench/textcontrol.py` is
  a plumbing tripwire for state reaching the uninformed sampler, and its 0.500 is
  an identity of that construction, not a measurement, so it cannot detect a
  leaky phrasing distribution (§10; a genuine control is issue #27).
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

1. A falsifiable, measurable comparison between semantic and
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
status: candidate            # not yet admitted; see the caveat below
```

Preconditions are **shell probes**, not prose and not Python callables. Probes
survive serialization into the committed library, are reviewable in a diff, and
can be executed by the runtime without importing program code. A reviewer can
verify a dispatch decision by hand, which would not be true of an embedding
score.

Parameters keep one program applicable to many repositories: the library stores
*knowledge*, not a transcript of one repository's history.

**Illustrative caveat:** the YAML above is a shape, not an admitted program. The
body in particular is not claimed correct — `git stash pop` after a rebase can
conflict, and a real program would have to handle that. No program has yet been
through admission.

### Lifecycle

```
candidate ──admission passes──▶ admitted ──postconditions fail──▶ demoted
    │                                                     │
    └──admission fails──▶ (not stored;            two mismatches
                           recorded as data)            ▼
                                                  quarantined
```

Nothing is deleted. A program that mis-fired is the evidence for Claim 2's
numerator, and removing it would erase the result.

---

## 6. Admission: the two-sided gate

A program becomes replayable only when **both** halves of its contract are
demonstrated:

```
POSITIVE   on N freshly faulted sandboxes: body runs, postconditions hold.
           Failure -> not admitted.

NEGATIVE   on sandboxes it must NOT claim: every unrelated state (clean
           worktree, upstream already merged, different fault injected)
           must be REJECTED by the preconditions.
           A precondition set that accepts everything is a DEFECT, not a
           convenience -- such a program fires on unrelated states, which is
           exactly the mismatch failure this project measures.
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
{arm, task_id, fault_type, occurrence_index, seed,
 tokens_in, tokens_out, cached_tokens_in, llm_calls, wall_clock_s,
 outcome: success|fail|mismatch|fallback|refusal|invalid, timed_out,
 program_id, dispatch_score, admitted, refusal_reason, model}
```

- `occurrence_index` — 1 for the first time this fault type is seen, 2 for the
  second, and so on. Grouping by it produces the headline curve.
- **Denominator rule.** `fail`, `mismatch`, `fallback` and `refusal` all carry
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

A dispatch decision costs no LLM call — arm 3 evaluates predicates, arm 2 does one
embedding lookup — so the pair count is chosen to make the comparison adequately
powered rather than to fit a budget.

**The episode loop is retained only as a demonstration, explicitly underpowered:**

```
5 faults × 4 occurrences × 3 arms = 60 episodes   (demo, UNDERPOWERED)
```

It is labelled underpowered wherever it appears and excluded from the primary
claim. Its value is showing the harness works end to end, not producing a result.

Seeds are split into disjoint admit / tune / eval sets and every arm is routed
through the same (fault, seed) pairs, so the comparison is paired rather than
between-populations. The unit of analysis is the fault seed, not the episode:
occurrences 2-4 are **held-out variants** of a fault (different branch names,
file sets, conflict positions, submodule states), or they are relabelled
"replays" and excluded from independence claims.

### Figures

**Figure 1 — mismatch vs coverage.** The primary figure. Both dispatchers swept
across acceptance thresholds; mismatch rate against coverage, Wilson intervals at
each operating point, and the pre-registered coverage point marked.

**Figure 2 — cost vs repeat (secondary).** Mean tokens and LLM calls per episode
against `occurrence_index`, one line per arm, from the underpowered demo. Reported
as a cost model, not as a contribution.

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
   disjoint admit / tune / eval sets; episodes paired by (fault, seed).
3. **Power statement:** required — the detectable effect size at the chosen pair
   count, coverage points, and alpha.
4. **Secondary metrics:** tokens and LLM calls per episode by occurrence index
   (the cost model); compile success rate; fallback rate; guard refusal rate. The
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

---

## 8. Failure handling

Rule: **no silent retries, no invisible costs.** Every degradation is attributed
to an arm and recorded with a reason.

| event | action | recorded as |
| --- | --- | --- |
| replay misses postconditions | demote program; fall back to ReAct **for this episode only**; fallback tokens attributed to the arm | `mismatch` |
| same program mismatches twice | withdraw from dispatch; retain for analysis | `quarantined` |
| compile fails admission | not stored; episode keeps its token cost | `candidate`, `admitted=false` |
| guard refuses the body | no execution; fall back to ReAct | `refusal` + `refusal_reason` |
| replay exceeds timeout | process killed, sandbox destroyed | `fail`, `timed_out` |
| no program applies | solve with LLM, compile, admit | `fallback` (expected, not a failure) |
| provider error / rate limit | capped backoff retry | `fail`, partial token spend retained |
| sandbox build fails | episode invalidated, counted | `invalid` |

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
| Generated body writes outside its environment | guard refuses paths outside `env_root`; `HOME` is redirected into the sandbox and the environment is scrubbed |
| Generated body force-pushes to a shared remote | guard refuses pushes to any remote not recognised as a sandbox |
| Generated body is destructive *inside* the sandbox | **accepted** — that is what the sandbox is for; the sandbox is destroyed afterwards |

**Structural protections, not just screening:**

- Phase 1 never points a replay at a real repository. Admission, benchmarking,
  and replay all run on disposable sandboxes.
- The replay timeout bounds damage from a hung or looping body.
- `runtime/replay.py` cannot reach `provider` (enforced by test), so a replay
  cannot be talked into asking for help.

**Residual risk, accepted and documented:** a generated body may perform
destructive-but-permitted actions within its sandbox, and network isolation on
macOS is best-effort (`sandbox-exec` where available, environment scrubbing
otherwise) rather than kernel-enforced. Running compiled programs against real
repositories requires human review of each program and is explicitly out of
scope; the guard is a seatbelt, not a sandbox boundary.

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
                cannot certify the phrasing distribution. The informed regime
                is a genuine measurement: 0.962 / 0.945 -- the boundary
                condition where the wording nearly determines the resolution
                and the mechanism is not needed. Pinned by a positive control
                that fires on an intent whose informed wording fully determines
                the answer, so the control cannot pass by being a no-op. Only
                registered intents are measured; the three unconverted faults
                return a fixed sentence and are excluded (issue #25).
IMPORT GRAPH    replay cannot reach provider, directly or transitively.
                IMPLEMENTED AND PASSING (tests/test_replay_isolated_from_provider.py)
ZERO TOKEN      stronger than the import test: replay runs with a provider whose
                complete() RAISES. Any hidden call path fails loudly at the
                integration level, where the import test only sees statically.
GUARD TABLE     bodies that must be refused, one line each to extend.
LEDGER INTEGRITY  every episode writes exactly one record; denominators must be
                reconstructable from the ledger alone.
NO SILENT SKIP  a skipped test must carry the plan phase that implements it.
                A test suite that quietly skips is a suite that passes for the
                wrong reason.
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
| dispatch mechanism | executable preconditions | embedding-only — no state awareness, and is *hypothesized* to mis-fire on structurally different environments that read alike; testing that hypothesis is what the benchmark is for |
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

1. **Arm 2 may saturate.** A strong embedding model may make semantic dispatch
   nearly as good as preconditions on five well-separated faults. If so, Claim 2
   dies — and the design should add faults that are *phrased alike but
   structurally different*, which is where embeddings should fail and probes
   should not. Watch for this in phase 2, before the full run.
2. **Compile cost may dominate.** If compiling costs as much as several ReAct
   episodes, amortization needs many recurrences. The crossover point is the
   honest result — but it should be checked early, since it determines whether
   three occurrences is enough structure.
3. **Fault leakage.** Injected faults may leave detectable artifacts (a
   suspiciously named branch, a telltale commit message) that make recognition
   artificially easy. Phase 1 must include an inspection step for this; no such
   check is implemented yet (issue #27).
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
   state-decided resolutions. Tracked in issue #25, and enforced rather than
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
will mis-fire less often than embedding dispatch, where mismatch is scored as an
outcome orthogonal to episode success. The mechanism is 1972; **that comparison
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
