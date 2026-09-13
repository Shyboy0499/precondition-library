# precondition-library — design of record

**Date:** 2026-09-13
**Status:** design approved, implementation not started
**Author:** Shyboy0499

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

**Claim 1 (secondary).** Tokens and LLM calls per episode fall across repeated
occurrences for the compiled arms and stay flat for the ReAct baseline, at
matched success rate — with cost per success reported alongside cost per episode
(§7), since an arm that succeeds more often may legitimately spend more.

**Claim 2 (primary).** At matched library size, precondition dispatch fires a
program that then fails its postconditions — a *mismatch* — less often than
semantic dispatch.

Claim 2 is primary deliberately. Claim 1 is close to obvious, and a project that
leads with it invites the response "so, caching". Declaring the harder claim
primary now means a null result cannot be quietly reframed as a win.

### What would falsify this

- **Compilation only pays on the 5th recurrence or later.** Then the honest
  conclusion is "not worth it for chores I run twice", and the crossover point
  is the result.
- **Semantic dispatch is already good enough.** Claim 2 dies; Claim 1 survives
  as a much less interesting finding.
- **Compiled programs rot as repositories drift.** Then the failure rate, not
  the cost curve, becomes the finding.
- **The injected faults leak a marker.** Arm 2 gets a free win and the
  comparison says nothing about real repositories.

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

- A product, a UI, or a DSH plugin. (A plugin wrapper is a *possible* phase 5,
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
   never validate Claim 1.
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
| `agents/react.py` | arm 1: observe → act → observe | provider, sandbox |
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
candidate ──admission passes──▶ verified ──postconditions fail──▶ demoted
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

```
5 faults × 4 occurrences × 3 arms = 60 episodes   (pilot)
```

Seeds are fixed and shared: **every arm faces byte-identical environments**, so
episodes are paired by (fault, seed) and the comparison is within-episode rather
than between-populations. Each arm builds its library from empty and runs
occurrences in order, so an arm cannot benefit from a program compiled against a
later state.

### Figures

**Figure 1 — cost vs repeat.** Mean tokens and LLM calls per episode against
`occurrence_index`, one line per arm. ReAct should be flat; the compiled arms
should fall. The crossover point is the honest headline.

**Figure 2 — mismatch comparison.** Mismatch rate, arm 2 against arm 3, with
Wilson intervals and explicit denominators.

### Pre-registered analysis

Written here, before any data exists, to prevent the analysis being chosen after
seeing the results:

1. **Primary metric:** the paired difference in mismatch rate (arm 2 − arm 3),
   over episodes where a program was dispatched, tested with McNemar's test on
   paired (fault, seed) episodes.
2. **Secondary metrics:** tokens and LLM calls per episode by occurrence index;
   compile success rate; fallback rate; guard refusal rate.
3. **Extension rule:** if the 95% interval on the primary difference spans zero,
   extend to 8 occurrences (120 episodes total) rather than re-analysing the
   pilot subset differently. If it still spans zero, the reported result is
   "no difference detected at this N", with the interval shown.
4. **Tuning discipline:** arm 2's similarity threshold is tuned on a held-out
   seed set disjoint from the evaluation seeds, and the value used is written
   into every ledger line. An untuned control arm would be a straw man; a
   control arm tuned on its own evaluation set would be cheating. Both are
   avoided, and the record shows which was done.
5. **Failed episodes stay in the denominator**, with their partial token spend.
   Dropping them would make amortization look better than it is.
6. **Cost per success is reported alongside cost per episode**, because an arm
   that succeeds more often may legitimately spend more per episode.
7. **Invalid episodes are excluded from denominators but never hidden.** An
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
                that mean nothing. Enforced by tests/ before anything else.
DETERMINISM     same seed -> byte-identical faulted environment; different
                seeds -> genuinely different instances. Non-determinism would
                appear as variance between arms.
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

The zero-token test is the one that matters most: Claim 1 is a statement about
cost, and the most likely way to make it silently false is an import nobody
noticed. Both a static test and a runtime test guard it.

---

## 11. Phases

| phase | contents | exit criterion |
| --- | --- | --- |
| 0 | design, scaffold, invariants, CI | **done** — this document, committed skeleton |
| 1 | sandbox, 5 fault injectors, gold solutions, ReAct baseline, ledger, provider | a fault can be injected, solved by ReAct, checked, and recorded; checkers validated against gold |
| 2 | compile step, two-sided admission, both dispatch mechanisms | a program compiled from one episode fires correctly on a later episode of the same fault |
| 3 | replay runtime, guard, demotion path, zero-token test | replay of an admitted program completes with a provider that raises on use |
| 4 | 60-episode run across arms, ablation table, both figures | a table and a curve exist, with intervals and denominators |
| 5 (optional) | DSH plugin wrapper | out of scope unless phases 1–4 land |

---

## 12. Decisions and rejected alternatives

| decision | choice | rejected alternative and why |
| --- | --- | --- |
| axis of novelty | the agent's loop/architecture | embodiment (a daemon, a repo-resident agent) — appealing but the interesting question here is structural, and this is what makes a measurable claim possible |
| headline claim | compile-once, replay-without-model | self-modifying agent (Darwin-Gödel-style) — generations are serial and each needs a full evaluation sweep; 2–3 weeks buys ~20 generations, not enough to see a signal over noise |
| | | swarm of tiny agents — cheap per run but high variance, and a positive result is hard to attribute to any mechanism |
| | | memory-as-program — a real problem, but it needs long-horizon tasks that are themselves expensive to run |
| comparison | three arms (react / semantic / precondition) | two arms (react vs precondition) — cheaper, but then Claim 2 has no control and a reviewer is right to say semantic dispatch was never given a fair shot |
| dispatch mechanism | executable preconditions | embedding-only — no state awareness, so it mis-fires on structurally different environments that read alike |
| | | one monolithic growing program with a dispatcher — the most striking demo, but it rots, and it cannot ablate *which* mechanism helped |
| domain | branchy git maintenance chores | synthetic benchmark suite — cleanest ablation, but produces an agent nobody uses and leaves "does this matter" unanswered; chores were chosen because correctness is free to check and the recurrence is real |
| stack | standalone Python engine, own the loop | DSH plugin (TypeScript) — cannot ablate a loop the host owns; measuring loop cost from inside a tool is not possible |
| sandbox | disposable repos only | real forks — replayed programs execute unattended; real repositories are not an acceptable target for unreviewed generated code |
| benchmark episodes | manufactured by seeded fault injection | waiting for real faults to recur — 60 recurrences will not occur in three weeks, so the experiment could not reach N |

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
   artificially easy. Phase 1 must include an inspection step for this.
4. **Five faults may be too few** for a mismatch comparison with usable
   intervals. The extension rule in §7 covers it, at the cost of episodes.
5. **Model drift.** Provider-side model updates mid-experiment would confound
   everything. `model` is recorded per episode; a version change invalidates the
   affected run and requires re-running that arm.

---

## 13. Prior work and positioning

A literature sweep on agents that accumulate and reuse skills, workflows, and
plans — and on the older literature on planning, policy reuse, and case-based
reasoning, where "is a stored plan still applicable?" is a long-standing
question — is in flight. Its results determine the positioning section of the
README and may require restating the claims.

**Until that section is written, this document makes no novelty claim.** The
architecture and measurement design stand on their own as an experiment; whether
the delta from existing work is publishable is a separate question that is
answered in the README, not assumed here.

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
