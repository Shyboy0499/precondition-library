<p align="center">
  <strong>precondition-library</strong><br>
  An agent that compiles a task into a program, then decides whether to replay it<br>
  by <em>running checks</em> rather than by guessing that the task looks familiar.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2EA44F?style=flat" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/status-design%20phase%20%C2%B7%20nothing%20measured-B8860B?style=flat" alt="Status: design phase">
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat" alt="Python 3.12+">
</p>

> **Status: design phase.** The repository contains a documented skeleton, not a
> working agent. No benchmark has been run and no result is claimed. Everything
> below is a hypothesis with a stated way to falsify it.

## The idea in sixty seconds

An LLM agent re-derives the same solution every time it meets the same problem.
That is expensive and it is not what a competent engineer does: you work out how
to sync a fork with upstream **once**, then you keep the recipe.

So: after solving a task, the agent compiles its solution into a **program** it
can run again later with no model in the loop. Cost is paid once and amortized
across every recurrence.

The interesting part is not the caching. It is **how the agent decides a stored
program still applies**. Two ways, and this project exists to compare them:

| | mechanism | nature |
| --- | --- | --- |
| arm 2 | *this task looks like one I've seen* — embedding similarity | probabilistic |
| arm 3 | *this environment satisfies my program's preconditions* — executable probes | checkable |

Preconditions are real commands, not prose. Deciding whether a program applies
costs zero tokens and can be audited by reading it.

```yaml
# library/sync-fork-dirty-tree/program.yaml   (illustrative shape, not yet admitted)
intent: bring a fork into sync with upstream while preserving uncommitted work
parameters: [work_dir, upstream_remote, upstream_branch]

preconditions:
  - name: has_uncommitted_changes
    probe: 'test -n "$(git status --porcelain)"'
  - name: upstream_is_ahead
    probe: 'test "$(git rev-list --count HEAD..{upstream_remote}/{upstream_branch})" -gt 0'
  - name: not_mid_rebase
    probe: 'test ! -d .git/rebase-merge'

body: |
  git stash push -u -m pl-sync
  git fetch {upstream_remote}
  git rebase {upstream_remote}/{upstream_branch}
  git stash pop

postconditions:
  - name: upstream_contained
    probe: 'git merge-base --is-ancestor {upstream_remote}/{upstream_branch} HEAD'
  - name: no_residual_changes
    probe: 'test -z "$(git status --porcelain)"'
```

A program is only replayable after **two-sided admission**: it must satisfy its
postconditions on a freshly faulted sandbox, *and* its preconditions must reject
negative sandboxes — environments where firing would be wrong. A precondition
that accepts everything is a defect, not a shortcut.

## Why this needs an experiment rather than an opinion

The obvious objection: *isn't semantic similarity good enough?* Possibly. That
is why arm 2 exists and is tuned before it is compared, and why the project
reports a mismatch rate rather than an anecdote.

Three arms, each building its library from empty, each facing identical seeded
environments:

| arm | library | dispatch | role |
| --- | --- | --- | --- |
| 1 `react` | none | — | baseline: full LLM cost per episode |
| 2 `semantic` | yes | embedding similarity | control: the obvious approach, tuned |
| 3 `precondition` | yes | executable preconditions | this project's claim |

**Claim 1.** Tokens and LLM calls per episode fall across occurrences for the
compiled arms and stay flat for ReAct, at matched success rate.

**Claim 2.** At matched library size, precondition dispatch mis-fires — fires a
program whose postconditions then fail — less often than semantic dispatch.

The task family is branchy git maintenance work: preserving uncommitted work
while syncing upstream, recovering a diverged branch, following an upstream
branch rename, re-pinning a drifted submodule, resolving a conflict inside a
generated lockfile. Each is chosen because the correct recovery *depends on
state*, so it cannot be aliased to a one-liner — and because correctness is
checkable by git alone, with no model in the scoring loop. Episodes are
manufactured by seeded fault injection into disposable sandboxes.

## What would falsify this

Stated up front, because a claim that cannot lose is not a claim:

- **The crossover arrives too late to matter.** If compilation only pays off on
  the fifth recurrence, the honest conclusion is "not worth it for chores I run
  twice".
- **Semantic dispatch is already good enough.** Falsifies claim 2, and reduces
  the project to the much less interesting claim 1.
- **Compiled programs break as repositories drift.** If programs rot faster than
  they amortize, the failure rate — not the cost curve — becomes the finding.
- **The faults leak a marker.** If injected faults are trivially recognisable,
  arm 2 gets a free win and the comparison says nothing about real repos.

## Layout

```
src/precondition_library/
├── program.py       the unit of reuse: intent, parameters, pre/postconditions, body
├── provider.py      the only module allowed to talk to an LLM
├── signatures.py    how a task and its environment state are described
├── sandbox.py       disposable repos for episodes
├── library.py       storage, two-sided admission, both dispatch strategies
├── tasks/faults/    seeded fault injectors, one module each
├── agents/
│   ├── react.py     arm 1
│   ├── compile.py   solved task -> candidate program
│   └── dispatch.py  arms 2 and 3 — the experiment
├── runtime/
│   ├── replay.py    runs programs; structurally cannot import provider
│   └── guard.py     screens model-authored code before it executes
└── bench/           ledger, episode runner, ablation report
```

`library/` holds admitted programs and **is committed on purpose** — it is the
artifact, and its git history records programs being demoted after they
mis-fired. `bench/gold/` holds hand-written solutions used to prove the
ground-truth checkers work before any agent result is believed.

One structural invariant is enforced by test rather than by convention:
`runtime/replay.py` must not be able to reach `provider`, directly or
transitively. If a replay episode could spend a token, claim 1 would be void, and
that is worth a failing test rather than a footnote.
([`tests/test_replay_isolated_from_provider.py`](tests/test_replay_isolated_from_provider.py))

## Roadmap

| phase | contents | state |
| --- | --- | --- |
| 0 | design, scaffold, invariants, checkers | **this commit** |
| 1 | sandboxes, fault injectors, gold solutions, ReAct baseline, ledger | not started |
| 2 | compile step, two-sided admission, both dispatch mechanisms | not started |
| 3 | replay runtime, guard, demotion path | not started |
| 4 | episodes across arms, ablation table, cost curve, mismatch comparison | not started |

## Prior work

Positioning against existing work on agents that accumulate and reuse skills,
workflows, and plans — and against the older literature on planning, policy
reuse, and case-based reasoning, where "is a stored plan applicable?" is a
long-standing question. **Filled in before this repository is announced**;
until then, treat novelty as unverified.

## License

MIT © 2026 Shyboy0499
