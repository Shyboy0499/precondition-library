# ADR-0027 — Register the dirty-tree intent, so `dirty_tree` is measured

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It narrows the spec's open risk 6 from three unconverted
  faults to two, and changes what every measured run includes.
- **Deciders:** repository owner (signed off on #189's registration step); recorded
  so each choice can be challenged

## Context

`dirty_tree` returned one fixed request sentence, so its text was a perfect class
label and it sat in `EXCLUDED_FROM_BENCHMARK` (open risk 6, #25). #189 converted it in
three steps, each of which left every measured number unchanged:

1. the fingerprint observes `dirty_files` and `untracked_upstream_collisions`, but
   `as_text` did not render them;
2. the injector selects one of three live states per seed -- `disjoint`, `same_file`,
   `collision` -- and the checker accepts a colliding untracked file kept at
   `<path>.local`, the one place both versions can survive;
3. `INTENT` (`keep_uncommitted_work_and_sync`) labels each state with the resolution it
   needs -- `stash`, `commit`, `aside` -- and declares the acceptable sets.

The acceptable sets are measured, not asserted: every gold body is replayed on every
state with its conditions stripped, and the checker's verdict must equal the declared
set (`tests/test_dirty_tree_intent.py`). On `disjoint` and `same_file` all three
resolutions pass; on `collision` only `aside` does, because a stash pop cannot restore
an untracked file over a tracked one and a merge meets an add/add conflict.

Registering the intent is the step that changes measurement, so it waited for the
owner.

## Decision

1. **`INTENT` is registered** in `tasks.registry.INTENTS`. `dirty_tree` leaves
   `EXCLUDED_FROM_BENCHMARK`, which now names `branch_renamed` and `lockfile_conflict`.
2. **`DIRTY_TREE_STATES` joins `STATE_GRID`** under the intent's name, so every
   grid-walking measurement -- the pair metric, the similarity probe, the text
   control, the coverage sweep -- includes its four states (three labelled, one
   benign).
3. **`as_text` renders every field**, `dirty_files` and `untracked_upstream_collisions`
   included. A field the rules decide on that arm 2 cannot read would make arm 2 blind
   by construction rather than by its mechanism.
4. **Tier 1 axes (ADR-0005):**
   - `content`: four flavours of every text the injector writes;
   - `untracked`: whether a non-colliding untracked file accompanies the `disjoint`
     and `same_file` states.

   `aside` varies on `content` only, because the collision *is* its untracked file.
   Instance identity is `dirty_tree/<resolution>/content=<i>/untracked=<presence>`.
5. **`bench.live.MEASURED_FAULTS` is derived from `ambiguous_intents()`**, so
   registering an intent puts its fault in the default live plan. The same derivation
   puts `dirty_tree` among `learn --fault`'s choices (ADR-0026).

## Consequences

**Accepted:**
- **Earlier arm-2 numbers are not comparable with later runs.** Every arm-2 text,
  in every family, gains two lines. On `diverged` and `submodule_moved` states both
  lines read `(none)`, which still moves lexical scores. Recorded baselines (ADR-0003,
  ADR-0004, ADR-0007) are history and are not recomputed. A new run measures its own.
- **Admission is stricter.** Admission's unrelated-fault class used to build one
  `dirty_tree` sandbox. It now builds one per distinct resolution, which is three. A
  `diverged` or `submodule_moved` program must refuse all three, and each admission
  builds two more sandboxes.
- **The smoke (admit) set draws no `stash` state.** Seeds 0, 1, 2 and 4 draw `commit`
  three times and `aside` once, so a library built on them holds no `stash` program.
  A `stash` state accepts `commit` and `aside` too, so a fire of either is correct
  there. The set is not changed to suit one fault: it is pre-registered.
- **`aside` cannot exceed the instance target.** Its one axis has four values, so
  the eval set builds exactly four `aside` environments, the owner's target. A fifth
  needs a Tier 2 axis (file names), which needs parameter binding first (#6).

**Gained:**
- **A third measured family, with an acceptable-set shape neither existing family
  has.** On `diverged` every state accepts merge and rebase. On `submodule_moved`
  exactly one resolution per state is acceptable. On `dirty_tree`, two states accept
  all three resolutions and one accepts only `aside`. The wrong fire it tests is the
  in-place sync on a state where an untracked file blocks upstream's.
- **The archetype fault is measured.** The fault's own docstring calls it the
  archetype of the whole project.
- **The live demo grows.** The eval set builds 61 environments, up from 47. The
  runnable episode demo grows from 24 to 36 episodes.

**New obligations:**
- Any later fault converted the same way (#190, #191) follows this pattern:
  - fields observed but not rendered;
  - states and checker;
  - an intent pinned by replay;
  - registration in a separate change, recorded here or in a successor.
- Every document that counts measured or excluded faults is pinned by
  `tests/test_declared_state.py`'s `EXCLUDED_FROM_BENCHMARK` claim, which now
  expects two.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Register the intent but keep the two fields out of `as_text` | Arm 2 would be scored on states whose deciding facts it cannot read. Its failures would then measure the rendering, not text-similarity dispatch, and Claim 2's comparison would be rigged against it. |
| Render the fields only for `dirty_tree` states | `as_text` is one rendering for every state, by design: a per-family rendering would let the text carry the family, a label arm 2 is not given. |
| Change the smoke set so the admit set draws a `stash` state | The seed sets are pre-registered (spec §7). Moving them after seeing what one fault draws is the analysis-after-results the registration forbids. |
| Keep `MEASURED_FAULTS` a literal and add `dirty_tree` by hand | A literal is a second place to keep in sync with the registry. The registry is the single place measurability is decided. |

## What would reverse this decision

- A replay shows the checker accepting a resolution the declared set excludes, or
  refusing one it includes. The acceptable sets would then be wrong, and every
  mismatch counted on this family with them.
- The injected states turn out to carry an artifact that names the resolution, the
  leak open risk 3 describes. The fault would then return to `EXCLUDED_FROM_BENCHMARK`
  until it is fixed.
