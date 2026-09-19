<p align="center">
  <strong>precondition-library</strong><br>
  Does deciding what to replay by <em>running checks</em> beat deciding by <em>similarity</em>?<br>
  A benchmark for an open measurement in skill reuse: which replay decision mis-fires less.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2EA44F?style=flat" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/status-mechanism%20demonstrated%20%C2%B7%20primary%20claim%20unmeasured-B8860B?style=flat" alt="Status: mechanism demonstrated, primary claim unmeasured">
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat" alt="Python 3.12+">
</p>

> **Status: the mechanism is demonstrated; the primary claim is not measured.**
> One smoke pass has run against a real model and is reported in
> [First demonstration](#first-demonstration): a compiled program is replayed with
> zero LLM calls on a later occurrence of the same state, and the compiled arms'
> cost falls while the baseline stays flat. That demonstrates the mechanism, not
> the claim — the pre-registered comparison (mismatch at matched coverage over
> labelled dispatch pairs, issue #5) has not been run, and the seeds are the smoke
> set rather than the eval set. Nothing below should be read as a result, and
> everything else here is a hypothesis with a stated way to falsify it. The
> apparatus is implemented and its suite is green in
> [CI](https://github.com/Shyboy0499/precondition-library/actions/workflows/ci.yml)
> — but an implemented apparatus is not a result.
>
> Per-module status is deliberately not restated below, because prose that
> describes the code drifts the moment the code moves (CONTRIBUTING rule 5).
> Every stub and every skipped test is declared and asserted against the code in
> [`tests/test_declared_state.py`](tests/test_declared_state.py), and what is
> outstanding is in the [issue tracker](https://github.com/Shyboy0499/precondition-library/issues).
> Those are the places to look for what is done.
>
> The design was **reframed on 2026-09-13** after a prior-art sweep and a hostile
> method review. The reasoning, and the claims that were dropped, are recorded in
> [`docs/decisions/ADR-0001-reframe-after-prior-art.md`](docs/decisions/ADR-0001-reframe-after-prior-art.md).

## What this is not

Stated first, because the prior art is real and the honest framing depends on it:

| Not claimed | Because |
| --- | --- |
| That compiling a task into a persistent program and replaying it without an LLM is novel | Already published: PreAct, SkillDroid, and Auto each compile a trace and replay it cheaply or with no per-step LLM calls (see [Prior work](#prior-work)). |
| That dispatching a cached plan by testing **executable preconditions** is a new mechanism | It is MACROPS, 1972: a cached generalized plan is dispatched by testing precondition *kernels* against live state, with an explicit replan fallback. |
| That "the most similar case is not the most reusable" is a new insight | Smyth & Keane argued it in 1998, in a peer-reviewed journal, at length. |
| That these token counts are a **cost** | They are tokens. Pricing input needs a rate table, and the provider's rates differ by peak and off-peak hours, so no currency figure is reported — input is metered as uncached, cache-read and cache-write so one can be computed once rates exist. |
| That a dispatch comparison has been made, or that any number here is a result for the primary claim | No dispatch comparison has been run. One smoke pass has (see [First demonstration](#first-demonstration)), and it demonstrates the mechanism rather than measuring the claim; the text-only control's informed AUC below is the other genuine measurement, and the uninformed 0.500 is an identity of the construction, not a measurement. |

Amortization is still what makes the project *useful* — it is an engineering
assumption here, not a finding. It is reported as a cost model, never as a
contribution.

## The open question

The mechanism is old. **The measurement is not.** No confirmed work runs this
head-to-head:

> **At matched dispatch coverage, does executable-precondition dispatch mis-fire
> less often than text-similarity dispatch — where a mis-fire is a program that
> fires, claims it succeeded, and did not?**

Two published results bracket the question without answering it — one deployed
gate and one benchmark:

- A production deterministic **executability gate** removes 59.4% of matched
  skill–message pairs and 59.1% of skill-description tokens, and in a
  gate-removed counterfactual the model selected a skill blocked as
  non-executable in **7.8%** of conversations (78/1,000). But the gate runs as a
  *cascade after* semantic recall: it can only prune candidates, never rescue one
  that recall missed. No head-to-head comparison is reported.
- A **retrieval-risk benchmark** measures top-K exposure of "harmful sibling"
  skills at HSR@3 **0.346–0.372** for public semantic retrievers, versus
  **0.007** for a controlled resolver. But that is retrieval *exposure*, not
  wrong-program *execution*, and again no precedence-versus-similarity dispatch
  comparison.

So the gap is narrow, and narrow is the point: it is small enough to close with
one person and one well-controlled experiment, and it is the only *measurement*
claim here that prior art does not already settle. The negative-sandbox admission
criterion is a second candidate, and its novelty is not confirmed.

## How the measurement works

The primary metric is **not** episode cost. An episode-level comparison is
confounded by LLM sampling variance and too underpowered to support the claim.
The measurement moves to **dispatch level**:

```
  labelled (repo-state, candidate-program) pairs
        │
        ├─ arm 3 needs no LLM:    pure predicate evaluation
        └─ arm 2 scores text similarity (lexical today; an embedding model
                behind the same seam is the intended replacement)
        │
  both dispatchers sweep their acceptance threshold
        │
  mismatch-vs-coverage curve, Wilson intervals, explicit power statement
```

Matching on **coverage** rather than library size is the load-bearing detail: a
dispatcher that fires on nothing achieves a perfect mismatch rate and is useless.
Both mechanisms are therefore swept across thresholds and compared at equal
coverage.

Two properties make a mis-fire visible rather than invisible:

1. **Mismatch is scored orthogonally to success.** A program that fires, fails its
   postconditions, and falls back to the agent may still end the episode
   "successfully" — which is exactly why success rate alone cannot detect a
   wrong-program fire. `mismatch` is its own outcome.
2. **Admission is two-sided.** A program is replayable only if it satisfies its
   postconditions on a freshly faulted sandbox **and** its preconditions *reject*
   negative sandboxes — states where firing would be wrong. A precondition set
   that accepts everything is recorded as a defect, not a convenience.

The request text is held to the same standard. It has two declared channels: the
shared **uninformed** `phrasings` list — what someone says when they do not know
what is wrong, or when nothing is wrong — and an **informed** entry in a
resolution's `variant_phrasings`, wording that reveals the situation. A
bag-of-words classifier trained on the text alone (`bench/textcontrol.py`, over
the test state grid, train n=120 / eval n=120 on disjoint seed sets) reports **AUC
0.500 for uninformed requests** on both converted intents and **0.962 / 0.945 for
informed requests** (`diverged`'s and `submodule_moved`'s intents, in that
order). The uninformed figure is an identity, not a measurement: on that channel
the sampler never consults state, so every state receives the same text for a
given seed, every positive has a negative with an identical score, and the AUC is
0.500 for *any* classifier and *any* phrasing list — including a deliberately
leaky one. The test on that regime is a **plumbing tripwire**: it fails if the
sampler starts consulting state, the regression that would restore the original
flaw; it cannot certify the phrasing distribution. The informed figure is the
genuine measurement — the boundary condition, where state-aware wording nearly
determines the resolution and the mechanism is not needed. An earlier draft
pooled the two regimes into one number (0.795–0.801, the control's pre-split
pooled figures) that described neither. The uninformed regime is gated; the
informed AUC is reported, never gated. Three of the five faults still return one
fixed sentence and are excluded from dispatch measurement, declared in
`tasks/registry.py`'s `EXCLUDED_FROM_BENCHMARK`.

The end-to-end episode loop survives as a small demonstration, explicitly
labelled underpowered. It is not the claim; its first run is reported in
[First demonstration](#first-demonstration).

## The artifact

Preconditions are executable probes, not prose and not embeddings:

```yaml
# library/sync-fork-dirty-tree/program.yaml   (illustrative shape, not yet admitted)
intent: bring a fork into sync with upstream while preserving uncommitted work
parameters: [work_dir, upstream_remote, upstream_branch]

preconditions:                      # ALL must hold to fire; run with no LLM
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

status: candidate   # admission has not run; nothing is replayable yet
```

Probes are shell commands rather than Python callables for three reasons: they
serialize into the committed library, they are reviewable in a diff, and the
runtime can execute them without importing program code. A reviewer can verify a
dispatch decision by hand — that would not be true of a similarity score.

The YAML above is a shape, not a solution. The body in particular is not claimed
correct: `git stash pop` after a rebase can conflict, and a real program would
have to handle that.

## The task family

Branchy git maintenance work, on disposable sandboxes. A fault is admitted only
if it **recurs**, is **checkable by git alone** (so scoring costs no tokens), and
is **branchy** — a fault solvable by one aliased command has a baseline cost of
zero, so nothing can be saved on it.

| fault | why it is branchy |
| --- | --- |
| `dirty_tree` | recovery depends on whether local edits conflict with upstream's changes |
| `diverged` | merge vs rebase vs discard depends on whether local commits are worth keeping |
| `submodule_moved` | recovery differs by whether the submodule is initialised, dirty, or absent |
| `branch_renamed` | requires noticing a remote-tracking branch disappeared and re-pointing the local one |
| `lockfile_conflict` | the right fix is regeneration, not marker-editing — and marker-editing *looks* like success |

`lockfile_conflict` is included as much for the negative sandboxes it supplies as
for its positive ones: it is the fault most likely to produce a program that
reports success while being wrong.

## What would falsify this

- **No difference at any coverage.** Then the honest finding is that executable
  preconditions buy no dispatch accuracy over text similarity in this domain, and
  the negative-sandbox admission factor becomes the whole contribution.
- **The faults leak a marker.** If injected faults are recognisable from the task
  text, similarity dispatch wins for the wrong reason. A phrasing that *names* a
  resolution is caught directly: `test_no_phrasing_names_a_resolution` rejects any
  whole-word variant id in either wording channel, which is precisely what the AUC
  gates cannot see — the uninformed one is fixed at 0.500 by construction, whatever
  the words say. A paraphrase that reveals the answer *without* naming it stays a
  review obligation rather than a test, and is stated as such in the spec.
- **Probes encode the answer.** If writing the precondition vocabulary requires
  the very knowledge being measured, the comparison is confounded by author
  effort rather than measured.
- **Text-similarity dispatch is already good enough.** Falsifies the claim, and
  leaves the benchmark as a null result with intervals attached — which is still a
  publishable-shaped outcome, and the reason this design is cheap to falsify.

## Layout

```
src/precondition_library/
├── program.py       the artifact: intent, parameters, pre/postconditions, body
├── provider.py      the only module allowed to talk to an LLM
├── signatures.py    how a task and its environment state are described
├── similarity.py    arm 2's seam: the text-similarity function it ranks with
├── sandbox.py       disposable repos for episodes
├── library.py       storage and both dispatch strategies; admission is in compile.py
├── tasks/
│   ├── spec.py      what a fault is: inject, task text, ground-truth checker
│   ├── intent.py    intents with more than one correct resolution
│   ├── registry.py  which task families have an experimental surface
│   └── faults/      seeded fault injectors, one module each
├── agents/
│   ├── react.py     arm 1: the baseline
│   ├── compile.py   solved task -> candidate program; the two-sided admission gate
│   └── dispatch.py  arms 2 and 3 — the experiment
├── runtime/
│   ├── replay.py    runs programs; structurally cannot import provider
│   ├── guard.py     screens model-authored code before it executes
│   └── probes.py    evaluates one probe; shared by admission and arm 3
└── bench/
    ├── ledger.py    the episode record
    ├── run.py       the episode runner and its repeat structure
    ├── pairs.py     labelled (state, resolution) pairs
    ├── splits.py    the pre-registered seed plan
    ├── textcontrol.py  the text-only control
    └── report.py    the ablation table and the two demo figures
```

`library/` holds every compiled program, admitted or not, and **is committed on
purpose** — it is the artifact, and the point of committing it is that a program
demoted after it mis-fired stays visible in the history.
`bench/gold/` holds the hand-written gold resolutions. What runs today for the two
ambiguous intents is form validation only: `sync_fork_with_upstream.yaml` and
`restore_submodule_state.yaml` must parse, be well-formed, cover every declared
resolution, and have distinct bodies (`tests/test_gold_programs.py`). No gold
checker has been executed against a sandbox — `tests/test_checkers_against_gold.py`
is skipped for every fault until the checker execution phase lands (issue #9),
because a checker cannot be validated without a state to check. (Probes did run
against sandboxes in the smoke pass below: admission's two-sided gate and arm 3's
dispatch both evaluate them, which is why this sentence is now about the gold
checkers only.)

One structural invariant is enforced by test rather than convention:
`runtime/replay.py` cannot reach `provider`, directly or transitively. It is worth
being precise about what that buys, because it is easy to overstate:

> **It is a cost invariant, not a safety invariant.** It guarantees a replay
> spends no tokens. It says nothing about whether a replayed program is safe.
> Safety is the guard's job, and the guard is a seatbelt, not a sandbox boundary.

## State of play

The pieces run end to end. `bench/run.py` injects a fault into a disposable
sandbox, one arm acts, the fault's own checker grades the result, and a ledger row
is written; `bench/report.py` turns the ledger into the ablation table and the two
demo figures. The suite covering that path is green in
[CI](https://github.com/Shyboy0499/precondition-library/actions/workflows/ci.yml),
and the seed sets a run would use are already fixed in `bench/splits.py`. **One
smoke run against a real model has happened** (see
[First demonstration](#first-demonstration)); it demonstrates the mechanism, but
the pre-registered comparison has not been run and nothing it produced is a result
for the primary claim.

What is done is deliberately not tracked here: a table in this file went stale the
last time a module moved, which is why it is gone. Status is recorded in two
places, both checked:

- **What the code is now.** Every stub and every skipped test is declared in
  [`tests/test_declared_state.py`](tests/test_declared_state.py), alongside a small
  claims table pinning the status sentences that reduce to a mechanical fact. CI
  fails when the declaration and the code disagree.
- **What is outstanding.** The
  [issue tracker](https://github.com/Shyboy0499/precondition-library/issues). The
  detail lives there, not here: #4, #5 and #6 gate the primary comparison
  (arm admission against one frozen library, the dispatch-level harness and
  coverage sweep, and the fault seed as the unit of analysis); #7, #8, #9 and #10
  are the control baselines, cost ledger, ground-truth decoupling and safety
  hardening behind them. Which faults are still excluded from dispatch
  measurement is declared in code, not here: `tasks/registry.py`'s
  `EXCLUDED_FROM_BENCHMARK`, asserted against every fault by a test.

## First demonstration

This is a **smoke pass**, not the measurement. Its job is to fail loudly on
wiring, not to produce a number; the pre-registered comparison — mismatch at
matched coverage over labelled dispatch pairs, issue #5 — was not run, and the
seeds are the smoke set from `bench/splits.py`, not the eval set.

**Provenance.** One pass, `deepseek-chat`, 48 episodes = 8 occurrences × 2 faults
(`diverged` and `submodule_moved`) × 3 arms, using the smoke seeds run twice
(`[0, 1, 2, 4, 0, 1, 2, 4]`). The raw ledger is
`.skillpilot/temp/smoke/previous-4/ledger.jsonl`; it is workspace-local and not
committed, its format is `bench/ledger.py`, and `bench/run.py` regenerates it.

Per arm over the whole pass:

| arm | episodes | correct end state | programs fired | replays | tokens |
| --- | --- | --- | --- | --- | --- |
| `react` — arm 1, the baseline | 16 | 16/16 | 0 | 0 | 285,607 |
| `semantic` — arm 2 | 16 | 15/16 | 5 | 2 | 302,060 |
| `precondition` — arm 3 | 16 | 16/16 | 5 | 5 | 276,431 |

"Correct end state" is the fault's own checker grading the final repository
state. A **replay** is an episode in which a program fired and the run spent
**zero LLM calls**; the seven replays across the two compiled arms each spent
0 tokens. 17 of 48 compiles were admitted, and 3 episodes carry a
`replay_failure_reason`.

Mean tokens per episode by occurrence index 1–8. These are the raw per-occurrence
means for the pass, not the figure `bench/report.py` reports. Two differences, and
both matter for reading the table below:

- **The reported figure is cumulative, not per-occurrence.** `bench/report.py`
  plots the running amortized tokens per episode with the break-even marked, because
  a per-occurrence mean is a snapshot: it cannot show whether an arm has yet paid
  back what compiling cost it. On this pass's numbers the two readings disagree
  about when the compiled arms cross the baseline, and the cumulative one is later.
- **It is computed over the replay occurrences only** (here occurrences 3–8 for
  `submodule_moved` and 4–8 for `diverged`, per the roles in the bullet below),
  because a variant is the learning pass. The table shows every occurrence so the
  learning pass is visible too.

| arm | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `react` — baseline | 22.7k | 13.4k | 11.4k | 19.2k | 13.6k | 23.5k | 17.4k | 21.7k |
| `semantic` — arm 2 | 25.8k | 25.7k | 22.4k | 25.9k | 18.2k | 18.4k | 8.7k | 5.8k |
| `precondition` — arm 3 | 20.2k | 38.0k | 8.1k | 30.8k | 9.2k | 12.2k | 10.2k | 9.4k |

LLM calls per occurrence on `submodule_moved`, where the zero-call replays are
plain to see:

```text
semantic      submodule_moved   13 13 13 13 10 10  0  0
precondition  submodule_moved   13 13  0 13  0  0  0  0
```

**What this shows.** A compiled program is replayed with no LLM calls on a later
occurrence of the same state, and the compiled arms' cost falls across
occurrences while the baseline stays flat — the baseline has no library, so it
must solve every episode with the agent and cannot fall. That is the mechanism,
demonstrated end to end against a real model.

**What it does not show, and must not be read as showing.**

- **It is not a result for the primary claim.** The pre-registered comparison
  (mismatch at matched coverage over labelled dispatch pairs, issue #5) did not
  run here, and these are the smoke seeds, not eval. No figure above measures
  the claim.
- **Five fires per compiled arm is not evidence of anything.** Of `semantic`'s
  five fires, four selected a resolution other than the episode's own correct
  one, and one of those ended in the wrong state (`semantic`, occurrence 7).
  `precondition`'s five fires all selected the correct resolution. Four
  mis-fires against zero is a *signal in the predicted direction* at n=5 fires
  per arm — not evidence. It is recorded because it is the honest state of the
  evidence, and a reader should know it exists.
- **Not every occurrence above is an independent observation** (issue #81). By
  the roles `bench/splits.py` now derives, occurrences 5–8 are all replays (the
  smoke seeds are run twice, so they revisit occurrences 1–4's states with the
  library those occurrences built), and two first-pass occurrences are replays
  too: seed 2 re-injects `repin` for `submodule_moved` (occurrence 3) and seed 4
  re-injects `overlapping_files` for `diverged` (occurrence 4). So the
  independent observations in the eight occurrences are 3 per family, not 8. The
  cost curve is computed over the replays — the accumulation is the effect being
  shown — and the mismatch comparison would be computed over the variants, which
  is why it cannot be read off this pass as a finding.
- **The cache figure is a confound, not a result.** Across the pass 864,098
  tokens were spent over 407 calls in 687s, and 73% of the input tokens were
  cache hits, so the baseline's real marginal cost is lower than the raw token
  counts above suggest.

## Installing

Two things the commands alone do not tell you:

- **Obtain the repository with `git clone`.** The suite proves it leaked nothing
  into this repository's own tree by comparing `git status --porcelain` against a
  snapshot taken at import (`tests/conftest.py`). A GitHub *Download ZIP* snapshot
  has no `.git` to compare against, so those tests **skip with that reason**
  instead of failing and the rest of the suite still runs — but the guarantee
  they carry is only meaningful in a clone.
- **Install the dev extra**, which is what provides `pytest`, `ruff`, `mypy` and
  `pandas` (see `pyproject.toml`). CI runs exactly these four gates:

  ```console
  git clone git@github.com:Shyboy0499/precondition-library.git
  cd precondition-library
  uv sync --extra dev
  uv run pytest                      # the suite
  uv run ruff check .                # lint
  uv run ruff format --check .       # formatting, including Python inside markdown
  uv run mypy src                    # types
  ```

Python 3.12 or newer is required (`requires-python` in `pyproject.toml`).

**Platform support.** CI runs `ubuntu-latest` only, so Linux is the only platform
this repository has evidence for. A Windows verification pass is recorded in
[#87](https://github.com/Shyboy0499/precondition-library/issues/87), which found
four deterministic defects there — two of which fail **silently**, reporting
success while doing nothing — and none of which the CI above could have caught.

## Running it

The invocation, the seed sets and the ledger format are fixed in the spec's
[§7, "The seed plan and the run invocation"](docs/superpowers/specs/2026-09-13-precondition-library-design.md#the-seed-plan-and-the-run-invocation);
that section is the source, and this one does not repeat it. Two properties matter
before anything runs:

- **The split is frozen in code, not chosen at run time.** `bench/splits.py` names
  the admit, tune and eval seed sets before any episode exists, because a split
  chosen after seeing scores is not a split. Changing a seed there is a
  pre-registration revision (CONTRIBUTING rule 8), not a config tweak.
- **Every occurrence carries a role, and the two figures use different ones.**
  `bench/splits.py` also derives, from the injector's own seed-to-resolution
  mapping, which occurrences are **variants** (the first sight of a resolution —
  the independent observations) and which are **replays** (later sights of one —
  what the cost curve is read from). `bench/run.py` writes the role onto every
  ledger row; `bench/report.py` computes the cost curve over the replays and the
  mismatch comparison over the variants, and says so in each figure. The
  arithmetic for the eval set is in the spec's §7: three variant occurrences per
  fault family, not forty.
- **The API key is the caller's.** `provider.py` reads no environment variables
  and no files; `DeepSeekProvider` takes the key at construction, and the spec's §7
  example is what passes `DEEPSEEK_API_KEY` into it. That is a deliberate boundary,
  not an omission — credential handling stays with the caller, and nothing in the
  package will find a key on its own.

## Prior work

Every citation below was checked against the source before publication — title,
authors, venue, and each attributed figure. Five attributions from the original
sweep were wrong and are corrected here rather than repeated.

**This is not independent review.** The check was performed by the author, so
treat it as a hygiene pass rather than external validation, and open an issue if
you find an error.

### Compile-once, replay-cheaply (settles the amortization claim)

| work | what it does | status |
| --- | --- | --- |
| **PreAct** — [arXiv:2606.17929](https://arxiv.org/abs/2606.17929) | Compiles a successful computer-use trace into a state-machine program with per-state verification predicates and parameter lifting; replays 8.5–13× faster with no per-step LLM calls; documents a `cov=100%/score=0` "lossy replay" failure | single-author industry preprint; all figures checked against the paper by the author |
| **SkillDroid** — [arXiv:2604.14872](https://arxiv.org/abs/2604.14872) | Compiles GUI trajectories into parameterized templates; replays with zero LLM calls; 49% fewer LLM calls, 2.4× speedup, 85.3% success | preprint. Note: its *dispatch* is a semantic matching cascade, so it is prior art for amortization **only** |
| **Auto: The AGI Compiler** — [arXiv:2607.04542](https://arxiv.org/abs/2607.04542) | Compiles witnessed-deterministic agent spans into signed WebAssembly, gated on differential replay, deopting to the paid agent on guard trip; 2,775 vs 17,692 µ$ over 300 items; 48.9% silently wrong under a loose guard | preprint; authors' own single-run measurements |
| **LATM** — [arXiv:2305.17126](https://arxiv.org/abs/2305.17126) (ICLR 2024) | A capable model builds a reusable parameterized tool from demonstrations; a cheaper model then invokes it | peer-reviewed. **Correction:** its replay phase still calls an LLM, so it is prior art for *cheaper* replay, not free replay |

### Precondition-based dispatch (settles the mechanism claim)

| work | relevance |
| --- | --- |
| **MACROPS** — Fikes, Hart & Nilsson, *Artificial Intelligence* 3(4):251–288, **1972** | Dispatches a cached generalized plan by testing executable precondition *kernels* against live state, with an explicit replan fallback. This is the intended mechanism, 54 years early. (1971 is the separate STRIPS paper.) |
| **Soar chunking** — Laird, Rosenbloom & Newell, *Machine Learning* 1(1):11–46, 1986 | Compiled rules cached and re-fired on matching conditions. |
| **Options** — Sutton, Precup & Singh, *Artificial Intelligence* 112(1–2):181–211, 1999 | An option's initiation set *plays the role* a precondition plays for a policy — an analogy, not an identity: options also carry a termination condition, which this project's preconditions do not. |
| **Adaptation-guided retrieval** — Smyth & Keane, *Artificial Intelligence* 102(2):249–293, 1998 | Argues, **paraphrased**, that it is often unwarranted to assume the most similar case is also the most appropriate for reuse. The original abstract wording is longer; this is not a quotation. |

### Bracketing the open question (does not settle it)

| work | what it shows | what it leaves open |
| --- | --- | --- |
| **Deterministic executability gating** — [arXiv:2608.01050](https://arxiv.org/abs/2608.01050) (Wix Helpmate) | A deterministic executability gate (exit-condition inversion, applied *after* semantic recall) removes 59.4% of matched skill–message pairs, 59.1% of skill-description tokens; 90.5% context reduction; 7.8% counterfactual mis-selection with the gate removed | The gate is a cascade after semantic recall, so it only prunes; no head-to-head comparison, no success or cost comparison, no tool-execution or customer-outcome result, 10 skills in one domain family. Preprint under review — it does **not** validate this project's claims. |
| **SameCapRisk-Bench** (v2 title: *Right Family, Wrong Skill*) — [arXiv:2606.10388](https://arxiv.org/abs/2606.10388) | HSR@3 0.346–0.372 for public retrievers; 0.128–0.182 for score-and-cluster; 0.007 for a controlled resolver; 1,190 skill-risk units, 1,686 queries | Measures retrieval *exposure* of risky siblings, not wrong-program *execution*; no predicate-key versus semantic-key head-to-head. **Correction:** these figures are v2's, under the v2 benchmark name — the earlier title `SkillResolve-Bench` has different, much smaller figures. |
| **alcheme-labs/dsh-experience-map** | States the thesis that similarity alone is not permission to reuse a procedure, with a "Preflight" gate; reports 65.9% token, 45.5% tool-call, and 46.2% step reductions | Brand-new (created 2026-09-12), 0 stars, and the reduction is a single self-run pilot the repository itself disclaims as an average and explicitly does *not* claim as more accurate than lexical retrieval. It contains `docs/decisions/m7-three-arm-evaluation.md` and `docs/release/BENEFIT_EVIDENCE.md` — an earlier, unverified claim that it publishes no comparison was wrong. |

If you know of work that *does* run the matched-coverage comparison, please open
an issue — that would be the most useful contribution anyone could make to this
repository, and it would let the project stop rather than duplicate it.

## License

MIT © 2026 Shyboy0499
