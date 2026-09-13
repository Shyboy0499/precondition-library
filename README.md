<p align="center">
  <strong>precondition-library</strong><br>
  Does deciding what to replay by <em>running checks</em> beat deciding by <em>similarity</em>?<br>
  A benchmark for an open measurement in skill reuse: which replay decision mis-fires less.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2EA44F?style=flat" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/status-design%20phase%20%C2%B7%20nothing%20measured-B8860B?style=flat" alt="Status: design phase">
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat" alt="Python 3.12+">
</p>

> **Status: design phase.** This repository contains a documented skeleton, not a
> working benchmark. No episode has been run, no figure exists, and **no result is
> claimed.** Everything below is a hypothesis with a stated way to falsify it.
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
| That any number in this repository has been measured | Nothing has been run. There is no figure, no table, and no `.jsonl`. |

Amortization is still what makes the project *useful* — it is an engineering
assumption here, not a finding. It is reported as a cost model, never as a
contribution.

## The open question

The mechanism is old. **The measurement is not.** No confirmed work runs this
head-to-head:

> **At matched dispatch coverage, does executable-precondition dispatch mis-fire
> less often than embedding dispatch — where a mis-fire is a program that fires,
> claims it succeeded, and did not?**

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
        └─ arm 2 needs one embedding lookup
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

The end-to-end episode loop survives as a small demonstration, explicitly
labelled underpowered. It is not the claim.

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
dispatch decision by hand — that would not be true of an embedding score.

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
  preconditions buy no dispatch accuracy over embeddings in this domain, and the
  negative-sandbox admission factor becomes the whole contribution.
- **The faults leak a marker.** If injected faults are recognisable from the task
  text, semantic dispatch wins for the wrong reason. A text-only classifier's AUC
  is the control that detects this.
- **Probes encode the answer.** If writing the precondition vocabulary requires
  the very knowledge being measured, the comparison is confounded by author
  effort rather than measured.
- **Semantic dispatch is already good enough.** Falsifies the claim, and leaves
  the benchmark as a null result with intervals attached — which is still a
  publishable-shaped outcome, and the reason this design is cheap to falsify.

## Layout

```
src/precondition_library/
├── program.py       the artifact: intent, parameters, pre/postconditions, body
├── provider.py      the only module allowed to talk to an LLM
├── signatures.py    how a task and its environment state are described
├── sandbox.py       disposable repos for episodes
├── library.py       storage, two-sided admission, both dispatch strategies
├── tasks/faults/    seeded fault injectors, one module each
├── agents/
│   ├── react.py     arm 1: the baseline
│   ├── compile.py   solved task -> candidate program
│   └── dispatch.py  arms 2 and 3 — the experiment
├── runtime/
│   ├── replay.py    runs programs; structurally cannot import provider
│   └── guard.py     screens model-authored code before it executes
└── bench/           ledger, episode runner, dispatch benchmark, report
```

`library/` holds admitted programs and **is committed on purpose** — it is the
artifact, and its git history records programs being demoted after they mis-fired.
`bench/gold/` holds the hand-written gold resolutions. The gold check runs today for
the two ambiguous intents: gold resolutions live in `sync_fork_with_upstream.yaml`
and `restore_submodule_state.yaml`, and `tests/test_gold_programs.py` validates
that they parse, are well-formed, cover every declared resolution, and have
distinct bodies. It is still skipped for the faults whose injection needs a live
sandbox (issue #4), because a checker cannot be validated without a state to check.

One structural invariant is enforced by test rather than convention:
`runtime/replay.py` cannot reach `provider`, directly or transitively. It is worth
being precise about what that buys, because it is easy to overstate:

> **It is a cost invariant, not a safety invariant.** It guarantees a replay
> spends no tokens. It says nothing about whether a replayed program is safe.
> Safety is the guard's job, and the guard is a seatbelt, not a sandbox boundary.

## Roadmap

| phase | contents | state |
| --- | --- | --- |
| 0 | design, scaffold, invariants, CI | done |
| 1 | reframe after review; correct the experimental design (issues #3, #4, #9) | current |
| 2 | dispatch-level benchmark harness, calibration sweep, power statement (#5, #6) | not started |
| 3 | baselines that make the control arm credible (#7); safety hardening (#10) | not started |
| 4 | run the benchmark; publish the mismatch-vs-coverage curves | not started |
| 5 | end-to-end agent demo, explicitly underpowered | not started |
| 6 | (optional) DSH plugin wrapper around the admitted library | not started |

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
