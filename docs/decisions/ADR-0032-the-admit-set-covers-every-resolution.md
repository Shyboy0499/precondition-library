# ADR-0032 — Build one episode per resolution, asking for it

- **Status:** accepted (2026-10-05)
- **Date:** 2026-10-05
- **Supersedes:** the admit set as `SMOKE_SEEDS` with each fault's own request (spec §7,
  "Design: the admit set builds the precondition vocabulary"). `SMOKE_SEEDS` stays the
  smoke set; the build no longer uses it unless a caller passes it as `seeds`.
- **Deciders:** repository owner. Asked for "the fix" after the sixth live run, when told
  that the build structurally could not give arm 2 a choice. Recorded so the choice can
  be challenged.

## Context

The primary claim may be worded as a win over text similarity only when arm 2 is a
usable baseline (spec §7 item 11, ADR-0007). The floor is measurable only when each
ambiguous intent's admitted programs offer at least two resolutions (#184). No live run
has measured it:

| run | admitted | intents with fewer than two resolutions |
| --- | --- | --- |
| 4 | 4 of 15 | four of five |
| 6 | 10 of 18 | three: `dirty_tree` only `stash`, `diverged` only `rebase`, `lockfile_conflict` none |

Run 6's Figure 1 was arm 3 at 0 of 115 mismatched against arm 2 at 99 of 111, with 0.19
detectable. The comparison exists; the rule that lets it be stated does not hold.

**The build cannot meet the rule, however good admission gets.**

- **The agent picks a resolution the state accepts, and most states accept several.**
  - Every `diverged` state accepts both `merge` and `rebase`.
  - Two of three `dirty_tree` states accept all three resolutions.
  - Two of three `branch_renamed` states accept `merge`.

  Given a request naming no resolution, the agent took `rebase` in all eight `diverged`
  build episodes of runs 4 and 6, and `stash` in every `dirty_tree` one.
- **Only some resolutions have a state that forces them** (a state whose acceptable set is
  that resolution alone). No `diverged` state forces any; `dirty_tree` forces only `aside`;
  `branch_renamed` only `merge`.
- **The four build seeds missed forcing states.** None of them injects `lockfile_conflict`'s
  `upstream_removed`, the only state that forces `take_upstream`.

## Decision

1. **The admit set is `bench.admit_set.ADMIT_SET`:** for each measured fault, one build
   episode per declared resolution. That is 14 episodes, against 20 before, plus the
   fallbacks of decision 5.
2. **Each episode's seed is a state labelled with its resolution**, and, where some state
   accepts that resolution alone, such a state. `tests/test_admit_set.py` pins both by
   building every seed's sandbox.
3. **Each episode's request asks for its resolution.** It is the fault's own phrasing for
   the seed, followed by a directive in a user's words, e.g. "Merge upstream into my
   branch and keep both histories." `run_episode(request=...)` carries it. Only the
   build passes one.
4. **The directives are build-only.** No measured request changes:
   - the phrasings the pairs and episodes draw from, and their test that no phrasing names
     a resolution, are untouched;
   - the dispatch arms never read a build request.
5. **Each resolution has a fallback seed** at the same kind of state, run only when the
   first episode admitted no program. With one episode per resolution, a single failed
   solve or refused program lost the resolution: in the eighth live run, `dirty_tree`
   lost `stash` to an inexpressible postcondition and `aside` to the tool budget, and
   was left with one. The build stops a resolution at its first admitted program, so it
   runs at most 28 episodes and, when most first episodes admit, close to 14.
6. **`build.json` records each resolution and the seeds it may try**; the build ledger
   records which ran. `build_library(seeds=...)` still runs the old shape, every seed with the fault's own
   request, for tests and for comparison with earlier runs.

## Consequences

**Accepted:**
- **A build request names its resolution.** The compiled program's text then tends to say
  what it does, and `compiled_from_task` records the request. That helps arm 2, which
  matches on text, so it can only make the baseline stronger.
- **The library no longer shows the agent's unprompted choices.** It shows what the agent
  builds when asked for each resolution. The vocabulary the claim needs is one where arm 2
  has a choice; the agent's preferences are measured in the episode stages, which keep the
  fault's own requests.
- **Build numbers are not comparable with runs 1-6.** Fewer episodes, different seeds,
  different requests.

**Gained:**
- **Arm 2's floor becomes measurable** whenever admission admits two programs per intent.
  That no longer depends on the agent varying its choice by luck.
- **A cheaper build:** 14 episodes instead of 20.

**New obligations:**
- A new resolution added to a measured intent needs an admit episode, which the coverage
  test enforces.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| More seeds with the fault's own request | The agent's choice does not vary with the seed where the state accepts several resolutions: eight of eight `diverged` episodes chose `rebase`. More seeds buy cost, not diversity. |
| Only forcing states | `diverged` has none, so its intent could still never offer two resolutions. |
| Evaluate the floor only on intents that offer two resolutions | It changes the registered analysis after seeing data, to make a claim reachable. That is the change a pre-registration exists to stop. |
| Put the directives in `variant_phrasings` | Those are measured requests. A request that names the resolution is the label, which the task-text control forbids. |

## What would reverse this decision

- Programs built from directed requests being admitted, then misfiring in the frozen
  benchmark at a higher rate than programs built from the fault's own requests. That
  would mean asking for a resolution yields programs that fit the request, not the state.
