# ADR-0028 — Register the renamed-branch intent, so `branch_renamed` is measured

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It narrows the spec's open risk 6 to one unconverted fault,
  and changes what every measured run includes.
- **Deciders:** repository owner. They decided on #190 that the trusted pre-fetch must
  not prune, and approved registering the intent without a further sign-off. Recorded
  so each choice can be challenged.

## Context

`branch_renamed` returned one fixed request sentence, so it sat in
`EXCLUDED_FROM_BENCHMARK` (open risk 6, #25). #190 converted it the way #189 converted
`dirty_tree` (ADR-0027), in three steps that each left every measured number unchanged:

1. **The fingerprint observes the branch wiring:** `tracked_branch`,
   `upstream_default_branch` and `local_branches`, read locally from the recorded
   remote `HEAD`. That ref is what the trusted pre-fetch brings current with `remote
   set-head --auto` (#205), so no prune and no `ls-remote` is needed. The fields were
   not rendered yet.
2. **The injector selects one of three live states**, and leaves each the way the
   pre-fetch leaves a checkout: fetched, upstream's `HEAD` recorded, nothing pruned.
   - `plain`: nothing local;
   - `local_work`: a local commit upstream lacks;
   - `name_taken`: a local branch already has the new name.

   The checker refuses losing either the local commit or the side branch. The harness
   reads upstream's default from the recorded `HEAD`, as a checkout does, so
   `{upstream_branch}` is the new name in both.
3. **`INTENT` (`follow_renamed_upstream_branch`) labels the states.** `plain` is
   `rename`, `local_work` is `merge` and `name_taken` is `retrack`. The acceptable sets
   are pinned by replaying every gold body on every state:

   | state | acceptable |
   | --- | --- |
   | `plain` | merge, rename, retrack |
   | `local_work` | merge |
   | `name_taken` | merge, retrack |

   Without a guard, `diverged`'s rules labelled the renamed `local_work` state
   `rebase`. They now refuse any state whose branch follows a renamed one.

## Decision

1. **`INTENT` is registered** in `tasks.registry.INTENTS`. `EXCLUDED_FROM_BENCHMARK` now
   names only `lockfile_conflict`.
2. **`BRANCH_RENAMED_STATES` joins `STATE_GRID`.**
3. **`as_text` renders `tracked_branch`, `upstream_default_branch` and
   `local_branches`** for every state, as ADR-0027 did for the dirty-tree fields.
4. **Tier 1 axes (ADR-0005):**
   - `name`: the new branch name, four values, drawn by the salt the fault always used;
   - `content`: four flavours of the texts each side writes.

   Both vary for every resolution. A branch name is a Tier 2 axis elsewhere because a
   program must bind it. Here it already is bound: `{upstream_branch}` is the recorded
   default. Instance identity is `branch_renamed/<resolution>/name=<n>/content=<i>`.
5. **`diverged`'s gold programs gain a precondition** that the local branch follows
   the branch upstream uses now. It holds on every `diverged` state. Without it, gold
   `rebase` fires on the renamed `local_work` state, where its body leaves the wiring
   stale.

## Consequences

**Accepted:**
- **Arm-2 numbers are not comparable across this change.** Every arm-2 text, in every
  family, gains three lines. Recorded baselines are history and are not recomputed.
- **Admission is stricter again.** The unrelated-fault class builds three
  `branch_renamed` states instead of one. A program that syncs commits without checking
  the wiring is refused there, as `diverged`'s gold `rebase` would have been.
- **Merge dominates this family, as it does `diverged`.** `merge` is acceptable on
  every labelled state. A dispatcher that always fires `merge` never mismatches here,
  and the comparison reports that rather than hiding it.

**Gained:**
- **A fourth measured family, on a different axis.** The others vary the environment's
  contents; this one varies its wiring.
- **The harness and a checkout agree on what upstream is** for a renamed upstream,
  which learning on a checkout (ADR-0026) depends on.
- **The live demo grows.** The eval set builds 91 environments, and the runnable episode
  demo grows to 48 episodes.

**New obligations:**
- Any intent whose resolutions sync commits must refuse a branch that follows a renamed
  one. `StateFingerprint.follows_a_renamed_branch` is the shared test.
- `tests/test_declared_state.py` now expects one excluded fault.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Prune in the pre-fetch, so the stale old name disappears | The owner decided against it on #190: pruning moves the user's remote-tracking refs. The recorded `HEAD` carries the same fact without moving anything. |
| Learn the new name with `ls-remote --symref` inside programs | On a checkout it would go through the mirror, which is built from the user's unpruned refs. The recorded `HEAD` is current and local, and a fingerprint must not fetch. |
| Keep the harness on `upstream/main` after a rename | A checkout of the same state derives the new name, so the two would fingerprint differently, and learning on a checkout would see states the harness never labelled. |
| Leave `diverged`'s rules unguarded | `diverged` would label a renamed state `rebase`, and pair metrics would score a resolution the renamed state's checker refuses. |

## What would reverse this decision

- A replay shows the checker accepting a resolution the declared set excludes, or the
  reverse.
- A real checkout whose pre-fetch cannot record upstream's `HEAD`, for example a remote
  that does not advertise it. The rename would then be unobservable without a fetch, and
  the family's states would not be what a user's repository shows.
