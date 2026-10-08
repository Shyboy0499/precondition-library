<p align="center">
  <strong>precondition-library</strong><br>
  Does deciding what to replay by <em>running checks</em> beat deciding by <em>similarity</em>?<br>
  A benchmark for an open measurement in skill reuse: which replay decision mis-fires less.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2EA44F?style=flat" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/status-primary%20claim%20measured%20%C2%B7%203%20replicates-2EA44F?style=flat" alt="Status: primary claim measured over three replicate builds">
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat" alt="Python 3.12+">
</p>

> **Status: the primary claim is measured, at pair level, over three replicate builds.**
> At matched dispatch coverage, executable-precondition dispatch mis-fired on **0 of 563**
> fires across the three libraries, against text-similarity dispatch's **76–81%**; arm 2
> cleared its pre-registered baseline floor in the two replicates built on the final
> code. The numbers, their provenance and their limits are in
> [Primary result](#primary-result). What is **not** measured yet is everything at
> episode level -- the frozen benchmark, the admission factorial and the online arms --
> and an earlier smoke pass, [First demonstration](#first-demonstration), is kept as
> the record of the mechanism, not of the claim. The apparatus's suite is green in
> [CI](https://github.com/Shyboy0499/precondition-library/actions/workflows/ci.yml).
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
| That an episode-level comparison has been made | Only the pair-level primary metric has been measured ([Primary result](#primary-result)). The frozen benchmark, the admission factorial and the online arms have not been run at scale; the one smoke pass that ran them ([First demonstration](#first-demonstration)) demonstrates the mechanism and measures nothing. |
| That precondition dispatch beats text similarity by a margin a stronger arm 2 would keep | The shipped arm 2 is lexical (ADR-0003) and clears its floor only modestly -- a 95% lower bound of 0.401 against chance 0.333. The pinned embedding arm (#104) was measured on the same three libraries and did not narrow the gap (+0.77 to +0.90 against lexical +0.76 to +0.81), but it is no stronger on the floor (lower bounds 0.405 and 0.340), so it is a different text scorer, not a better one. Whether a scorer that clearly beats the lexical floor would keep the margin is still unmeasured. |

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
  arm 2 sweeps its threshold; arm 3, which has no score, is one operating point
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
0.500 for uninformed requests** on every converted intent and **0.962 / 0.945 /
1.000 / 1.000 / 1.000 for informed requests** (`diverged`'s, `submodule_moved`'s,
`dirty_tree`'s, `branch_renamed`'s and `lockfile_conflict`'s intents, in that order). The uninformed figure is an identity, not a measurement: on that channel
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
informed AUC is reported, never gated. Every fault now has a registered intent
(ADR-0027 to ADR-0029), so none is excluded from dispatch measurement;
`tasks/registry.py`'s `EXCLUDED_FROM_BENCHMARK` is empty, and would name any later
fault whose request is a fixed sentence.

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
and the seed sets a run would use are already fixed in `bench/splits.py`. Live runs
against a real model are tracked on #163 and #214. The early ones exercised the whole
pipeline -- build, frozen benchmark, Figure 1 from a compiled library, the online arms
-- at smoke scale, and each found defects that were then fixed; the first is written
up under [First demonstration](#first-demonstration). The eleventh to thirteenth are
the three replicate builds behind [Primary result](#primary-result). The episode-level
stages have not been run at the registered scale (`--episode-seeds 40 --replicates 3`).

What is done is deliberately not tracked here: a table in this file went stale the
last time a module moved, which is why it is gone. Status is recorded in two
places, both checked:

- **What the code is now.** Every stub and every skipped test is declared in
  [`tests/test_declared_state.py`](tests/test_declared_state.py), alongside a small
  claims table pinning the status sentences that reduce to a mechanical fact. CI
  fails when the declaration and the code disagree.
- **What is outstanding.** The
  [issue tracker](https://github.com/Shyboy0499/precondition-library/issues). The
  detail lives there, not here. The primary comparison's code is in place and #5
  stays open until the pre-registered full-scale run exists (the one command is in
  [Running it](#running-it)); #163 records the live runs so far. Using the library on
  a repository of your own is #181 (dispatch, and replay on confirmation) and #188
  (learning a program there).
  Which faults are still excluded from dispatch measurement is declared in code, not
  here: `tasks/registry.py`'s `EXCLUDED_FROM_BENCHMARK`, asserted against every fault
  by a test. Since #189, #190 and #191 (ADR-0027 to ADR-0029) every fault is
  measured, and the set is empty.

## Primary result

**The question**, as [The open question](#the-open-question) states it, measured as the
spec registers it (ADR-0022): Figure 1 over **400 labelled dispatch pairs** from the
eval seeds, uninformed regime, each arm's fires judged against the pair's acceptable
resolutions, arm 2 swept to arm 3's coverage. Three whole-run replicates (spec §7 item
2), each building its own library from the admit set (ADR-0032) with `bench.live
--primary-only`; no model call is made after the build.

| | replicate 1 (run 11) | replicate 2 (run 12) | replicate 3 (run 13) |
| --- | --- | --- | --- |
| programs admitted (two-sided) | 13 | 14 | 13 |
| arm 2's baseline floor (spec §7 item 11) | not measurable | **usable** (top-1 111/240, lower bound 0.401 > 0.333) | **usable** (111/240, 0.401) |
| arm 3: coverage, mis-fires | 187/400, **0/187** | 187/400, **0/187** | 189/400, **0/189** |
| arm 2 at matched coverage: mis-fires | 148/187 | 149/185 | 143/187 |
| difference (arm 2 − arm 3) | +0.79 | **+0.81** | **+0.76** |
| smallest detectable difference | 0.145 | 0.145 | 0.144 |
| embedding arm 2 (#104): floor | not measurable | usable (112/240, 0.405) | usable, barely (96/240, 0.340) |
| embedding arm 2 at matched coverage: mis-fires | 143/185 | 168/189 | 169/187 |
| difference (embedding arm 2 − arm 3) | +0.77 | **+0.89** | **+0.90** |

**What it shows.** Precondition dispatch never fired a program that the pair's state
did not accept; text similarity, at the same coverage, did so on roughly four fires in
five. The difference is about five times the smallest one the pair count can detect,
and it holds in every replicate. Where arm 2's floor is usable -- replicates 2 and 3 --
the claim may be worded as registered: a win over text similarity. Swapping arm 2 for the
pinned embedding scorer (#104) does not narrow the gap: it mis-fires on 77–90% of its
fires at matched coverage, the gap widens in replicates 2 and 3 and narrows by 0.02 in
replicate 1, and arm 3 is unchanged ([Embedding arm 2](results/replicates-2026-10-05/README.md#embedding-arm-2)).

**What it does not show.**

- **Replicate 1 may not be worded as a win.** Its library held one lockfile
  resolution, so arm 2 had nothing to choose between there and the floor could not be
  measured. It was also built on earlier code, before the fixes in #244 and #245;
  re-gated offline under the final admission, its figure is 0/187 against 141/186.
- **Arm 2 is a weak baseline, under both scorers.** The lexical arm's floor sits only
  0.07 above chance, and the embedding arm is no stronger on it: one more correct top-1
  in replicate 2, fifteen fewer in replicate 3, where its lower bound clears chance by
  0.007. The size of the gap is a statement about these two text scorers, not about a
  strong one.
- **Nothing at episode level.** Mis-fires that end in a wrong repository, cost, the
  admission factorial and the online arms are separate stages, not run here.
- **Arm 2b cannot separate the two.** At arm 3's coverage the soft vote's matched point
  is the hard rule itself, so Claim 2 keeps its wording without showing that requiring
  every probe adds anything over a vote.

**Provenance.** `deepseek-flash`; builds of 14–17 episodes spending 144k–204k uncached
input, 280k–372k cached input and 402k–539k output tokens each. Code: run 11 on main
`a6ff042`, run 12 on `d524978`, run 13 on `44a1ffc`. The per-run table, the re-gate and
the defects found on the way are in
[#214](https://github.com/Shyboy0499/precondition-library/issues/214#issuecomment-5999250801).

## First demonstration

The first smoke pass against a real model -- 48 episodes, two faults, three arms -- showed the
mechanism end to end: a compiled program replayed with zero LLM calls on a later occurrence, and
the compiled arms' cost fell across occurrences while the baseline stayed flat. It measured
nothing about the claim. Its tables, provenance and limits are in
[`results/first-demonstration.md`](results/first-demonstration.md).

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
[§7, "The seed plan and the run invocation"](docs/design/specs/2026-09-13-precondition-library-design.md#the-seed-plan-and-the-run-invocation);
that section is the source, and this one does not repeat it. Two properties matter
before anything runs:

- **The split is frozen in code, not chosen at run time.** `bench/splits.py` names
  the admit, tune and eval seed sets before any episode exists, because a split
  chosen after seeing scores is not a split. Changing a seed there is a
  pre-registration revision (CONTRIBUTING rule 8), not a config tweak.
- **Every occurrence carries a role, and the two figures use different ones.**
  `bench/splits.py` derives, from the injector's own seed-to-instance mapping,
  which occurrences are **variants** (the first sight of an instance — the
  independent observations) and which are **replays** (a genuine repeat of one —
  what the cost curve is read from). `bench/run.py` writes the role onto every
  ledger row; `bench/report.py` computes the cost curve over the replays and the
  mismatch comparison over the variants, says so in each figure, and carries the
  achieved instance count per resolution. The arithmetic for the eval set is in
  the spec's §7: 32, 15, 14, 30 and 28 variant occurrences (119 distinct
  environments across the five faults), not forty seeds.
- **The API key is the caller's.** `provider.py` reads no environment variables
  and no files; `DeepSeekProvider` takes the key at construction, and the spec's §7
  example is what passes `DEEPSEEK_API_KEY` into it. That is a deliberate boundary,
  not an omission — credential handling stays with the caller, and nothing in the
  package will find a key on its own.

**A whole live run is one command.** `bench/live.py` chains the stages in the spec's
order: build and gate the frozen library twice, learn arm 2b's threshold on the tune
seeds, run the frozen benchmark and the admission factorial, produce Figure 1 from
the library's own matchers, and run arms 1 and 1b online. Every artifact goes into one
fresh directory, with `summary.txt` and `summary.json` saying what ran and where each
artifact is:

```bash
uv run python -m precondition_library.bench.live \
  --api-key-env DEEPSEEK_API_KEY --out ../live-run   # or --api-key-file PATH
```

You name where the key is, so the package still finds none on its own.
`--episode-seeds` (default 4, the first live run's; the plan is 40) sizes the
episode stages, `--replicates` (default 1; the plan is 3) repeats each of them as a
whole run, and `--skip-online` drops arms 1 and 1b. The registered plan is
`--episode-seeds 40 --replicates 3`. The summary also carries arm 2's baseline floor
(spec §7 item 11) and the instance-clustered interval over the episodes (ADR-0012).

## On your own repository

The library can also be used outside the harness, on a repository you already have
(issues #181 and #188). Nothing model-written ever reaches a real remote: the tool
fetches your upstream once, with your own git, into a local mirror, and every probe,
body and agent command then runs screened, without network where the host allows it,
and with your upstream read from that mirror; every other remote -- your own fork
included -- is unreachable. Commits it makes carry your git identity.

**Dispatch** reports which admitted program would fire on your repository and why,
probing a copy of it, and with `--replay` dry-runs it on a second copy, shows what it
did, and replays on your repository only after you confirm:

```bash
uv run python -m precondition_library dispatch --repo PATH --library DIR [--replay]
```

**Learn** has the agent solve a copy of your repository for a request in one of the
measured families, shows you what the solve did, and -- only if you confirm -- compiles
it and admits it through the same two-sided gate the harness uses, plus a check that it
fires where it was learned (ADR-0026). It calls a model, so it needs a key:

```bash
uv run python -m precondition_library learn --repo PATH --library DIR \
  --fault diverged --request "sync my fork with upstream" --api-key-env DEEPSEEK_API_KEY
```

A learned program is marked `learned_on: checkout`, and a measured run refuses any
library that holds one: the measurement stays harness-only.

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
