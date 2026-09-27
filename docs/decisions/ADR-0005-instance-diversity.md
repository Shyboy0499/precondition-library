# ADR-0005 — Parameterise each injected state along declared axes, and key independence on instance identity

- **Status:** proposed
- **Date:** 2026-09-27
- **Supersedes:** nothing (narrows the injector design and the `occurrence_role` rule recorded in spec §7 / revision 13; ADR-0001–0004 stand)
- **Deciders:** repository owner

## Context

Issue #86's measured finding: the injectors select among a small number of
hand-authored state shapes per fault, and the seed chooses **which shape**, not
the shape's content. Two seeds that select the same resolution therefore build the
same environment, so the mismatch comparison's unit of analysis — the environment
— is fixed by the number of shapes rather than by the number of seeds.

**The measurement.** Every seed the pre-registration uses — smoke `0,1,2,4`, tune
`1000–1015`, eval `2000–2039`, 60 seeds in all, from `bench/splits.py` — was built
as a real sandbox per fault and compared by
`precondition_library.bench.instance_diversity`. Two sandboxes are "the same
environment" when their working-tree file bodies, upstream tree, file names,
file/commit counts, conflict positions, submodule paths and branch wiring are
equal; a second count adds every ref and object id, so "identical" can be told
from "identical except commit SHAs". Reproduce with

```text
.venv/bin/python -m precondition_library.bench.instance_diversity
```

| fault | resolution | seeds | instances | with SHAs | varies within the resolution | fixed within the resolution |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `diverged` | `discard` | 30 | **1** | 1 | — | everything measured |
| `diverged` | `merge` | 19 | **1** | 1 | — | everything measured |
| `diverged` | `rebase` | 11 | **1** | 1 | — | everything measured |
| `submodule_moved` | `init` | 22 | **1** | 1 | — | everything measured |
| `submodule_moved` | `remove` | 21 | **1** | 1 | — | everything measured |
| `submodule_moved` | `repin` | 17 | **1** | 1 | — | everything measured |
| `dirty_tree` | (no resolution) | 60 | 2 | 2 | file bodies, file names, file count | the rest |
| `branch_renamed` | (no resolution) | 60 | 4 | 4 | branch names | the rest |
| `lockfile_conflict` | (no resolution) | 60 | 56 | 56 | file bodies, upstream tree | the rest |

**The issue is confirmed on the two measurable faults, and its example is
exact.** `diverged` seeds 0 and 4 both resolve to `merge`; the strict-`xfail` pin
`diverged-merge-0-4` in `tests/test_instance_diversity.py` fails on exactly that
pair today, and fails because the two environments are equal. The family offers
**3 content-distinct environments per measurable fault and 6 across the two** —
which is #86's "6 independent observations" — over 60 seeds.

**One correction to #86's wording.** The issue says two same-resolution seeds are
"the same environment differing only in commit SHAs". They do not differ in SHAs
either: the sandbox pins author and committer dates and identities
(`sandbox.py`), so the module's SHA-inclusive count equals its content count at
1 for every resolution above. The environments are byte-identical, which makes
the constraint slightly stronger than the issue stated, not weaker.

**The three excluded faults are not evidence against the rule.** Two of them
already vary content by seed (`dirty_tree` by whether an untracked file joins the
edit, `branch_renamed` by the new branch name, `lockfile_conflict` by the package
names and versions it writes). They still cannot carry a dispatch measurement,
because they return a single fixed request sentence and the text is the class
label (`EXCLUDED_FROM_BENCHMARK`, issue #25). So the family already contains the
mechanism this ADR proposes — it is simply not applied to the faults whose
resolutions the comparison is about.

**Why this is the binding constraint.** The mismatch comparison's unit of analysis
is the environment (spec §7, §12 "unit of analysis"). A second occurrence of a
resolution is an independent observation only if it is a second environment; today
it is the first one with a different request text, which is exactly the
pseudo-replication §7 forbids. More seeds, and the pair-level harness of #5, both
multiply observations without changing how many environments exist. The honest
consequence, already in the spec's underpower note, is that no interval can be
attached to Claim 2 at N=6.

**What makes diversity safe is a declared invariant, not care.** A resolution is a
pure function of the `StateFingerprint` (`diverged`: `has_local_only_commits`,
`local_touched_files`, `conflicting_files`; `submodule_moved`:
`upstream_still_references_submodule`, `submodule_initialised`,
`submodule_pin_matches_upstream`). A varied instance must still satisfy the same
predicate, or the correct answer changes and every label downstream is wrong. The
draw has to be constrained by that fact, and checked against it.

## Decision

1. **Vary the content of each state shape, not the number of shapes.** Each fault
   declares a set of **axes** with value pools and a per-seed draw (through the
   existing `sample_index`), and the injector builds the shape from the drawn
   values. The number of resolutions and their decision rules do not change.

2. **Declare, per resolution, which axes may vary and which must not.** An axis
   may vary for a resolution only if that resolution's `decided_by` predicate is
   invariant under it. The safe set, which the implementation must state per fault
   and a test must check:

   - `diverged` / `discard`: upstream file names and contents, upstream commit
     count, the number of empty local commits, commit-message pools. Every draw
     keeps `has_local_only_commits and not local_touched_files`.
   - `diverged` / `rebase`: the local and upstream file pools, kept **disjoint**,
     their counts, the hunk positions, commit counts. Every draw keeps
     `local_touched_files` non-empty and `conflicting_files` empty.
   - `diverged` / `merge`: the shared file name(s) and counts, the hunk positions
     **inside the shared file** (the rule is file overlap, not hunk overlap, so
     hunk position is free), commit counts.
   - `submodule_moved` / `init`, `repin`, `remove`: the submodule path drawn from
     a declared pool — the probes already bind `{submodule_path}` — the parent
     repo's file names and counts, and commit counts.
   - **Not drawable:** any axis that can move the local edit into a file upstream
     also touched (which turns `rebase` into `merge`), remove the overlap (which
     turns `merge` into `rebase`), or change the submodule's initialised /
     still-referenced / pin-equal facts. These are relabellings, not variation.

3. **A build-time invariant re-derives the resolution and refuses a mismatch.**
   After injection, `build_sandbox` observes the `StateFingerprint`, computes the
   intent's correct variant, and raises if it is not the resolution
   `variant_for_seed` declared for that seed. This is what makes decision 2
   enforceable: an axis draw that flips a predicate fails the build instead of
   feeding a mislabelled instance into the comparison.

4. **`FaultSpec.variant_for_seed` keeps its meaning; instance identity is a new,
   separate notion.** `variant_for_seed(seed)` still answers "which resolution is
   correct at this seed", and `admit`'s same-intent negative class and the ledger
   keep that reading. A new `instance_for_seed(seed)` returns the **instance
   identity** — the resolution plus the drawn axis values, as a stable string —
   from the same draw `inject` uses, so the two cannot disagree. `build_sandbox`
   records it on the `Sandbox` beside `injected_state`, the harness-owned place
   `#103` established.

5. **Independence is keyed on instance identity, not resolution.**
   `bench/splits.py`'s `occurrence_roles` currently marks an occurrence `variant`
   the first time a **resolution** is seen. It must mark it `variant` the first
   time an **instance** is seen and `replay` only on a genuine repeat of one. A
   second seed on a different instance of the same resolution is a new independent
   environment, and counting it as a replay is the defect this ADR removes. The
   ledger's `occurrence_role` field does not change; the rule that assigns it does.

6. **The pre-registration's seed plan is restated in terms of independent
   environments.** The smoke/tune/eval **seed sets** do not change — changing them
   is a separate pre-registration revision (CONTRIBUTING rule 8). What changes is
   the arithmetic and its wording: the independent observations a set supports is
   the number of distinct instances its seeds build, computed from
   `instance_for_seed` before any episode runs, and the underpower note says so.
   At the measured state of the injectors that is **3 per measurable fault, 6
   across the two**, and the plan may not claim more until the injectors produce
   it. This ADR fixes the *approach*, not an instance count: the count is
   whatever the declared draw yields, and it is measured and reported.

7. **A fault that cannot achieve diversity is excluded from the comparison, not
   counted as though it varied.** If, after the axis declaration, a resolution has
   exactly one instance and no safe axis remains, that fault leaves the mismatch
   comparison the way `EXCLUDED_FROM_BENCHMARK` leaves it — named, with the reason
   — rather than contributing a nominal N it does not have. #86 names the
   submodule case as the example. On this reading it is *not* currently such a
   fault: its path and parent-repo content are safe axes. The rule is for the
   fault where the draw space collapses, and it is exclusion rather than padding.

8. **The report carries the achieved instance count per resolution.** The
   mismatch report gains, per fault and resolution, the number of independent
   environments actually built, read from `instance_for_seed`, beside the pair
   counts. A reader must not be able to take a larger seed count for more power.

9. **The strict-`xfail` test is the acceptance test.**
   `tests/test_instance_diversity.py::test_same_resolution_seeds_build_different_environments`
   builds two real sandboxes per measurable resolution and asserts their content
   signatures differ. It is `xfail(strict=True)` today, with a reason naming #86;
   the change that lands this ADR deletes the marker, and the work is not done
   while the marker remains.

## Consequences

**Accepted:** the injectors gain an axis declaration, a draw and a build-time
fingerprint check, so every fault module and its sandbox tests get larger, and a
build does one extra observation. More importantly, the cost model's "a replay is
free" property narrows: with instance diversity a program admitted on one instance
may not fire on a different instance of the same resolution, so the cost curve can
flatten less and must be read per instance. That is the honest reading of a
genuinely new environment, and it is a cost of the change rather than a defect in
it. Labels and ledger roles produced before this change keep their
resolution-keyed meaning and are not rewritten (CONTRIBUTING rule 5).

The largest cost is a sequencing constraint. Varying file names or the submodule
path changes what the probes and bodies must bind, so the axes cannot land before
`{submodule_path}`-style parameters cover them; a draw that the library cannot
bind would break dispatch rather than broaden it. The axis work and the parameter
coverage must land together, which is why this ADR scopes the direction before
the work is spent.

**Gained:** a new seed can be a new environment, which is what Claim 2's unit of
analysis needs; the independent N of the episode loop is no longer capped at the
number of hand-written shapes; and the label cannot break silently, because the
build-time invariant refuses a draw that changes the resolution.

**New obligations:** `instance_for_seed` must be pure and share one draw
definition with `inject` (the `state_for_seed` pattern); `occurrence_roles`, its
tests, `bench/splits.py`'s docstring arithmetic and the ledger documents move from
resolution to instance identity in the same change; the report prints the achieved
instance count per resolution; the gold programs and the admission
negative-class seeds are checked against every drawn axis; and the strict-`xfail`
marker is deleted when the property holds.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Author more shapes per resolution by hand | It raises the cap without changing the principle: a new seed is still a repeat of an authored shape, N is still the number of shapes, and 40 eval seeds would need 3×N hand-written repositories and 3×N checkers. Parameterising keeps one shape definition and draws instances from it. |
| Accept N=6, report a wider interval, and leave the injectors | The underpower note already says no interval is attachable at 6; accepting it decides that the episode loop cannot measure Claim 2 at any seed count, which is the outcome #86 exists to avoid. |
| Vary only cosmetic axes — commit messages, dates, SHAs | A different commit SHA is not a different environment (#86's own sentence), and the pin deliberately excludes SHAs so cosmetic variation cannot satisfy it. It raises a nominal count while adding no state a dispatcher must handle. |
| Draw axis values at random with no declaration | The correct resolution is a pure function of state, so an unchecked draw can flip a predicate — a `rebase` local edit moved into a file upstream touched becomes `merge` — and silently corrupt the label every number depends on. Decision 2's declaration plus decision 3's invariant is the guard. |
| Vary the request text instead of the environment | The environment is the unit of analysis, and the request text already varies and is measured separately (the informed/uninformed control). A new phrasing is not a new environment. |
| Convert the three excluded faults and count them instead | They are excluded because a fixed sentence makes the text the label, a different defect (#25). More instances do not give them a dispatch surface; counting them would inflate N with faults on which the comparison measures nothing. |
| Key independence on the seed rather than the instance | A seed is not the unit of analysis; the environment is. Two seeds on one instance are one observation — the pseudo-replication §7 already forbids and decides against ("unit of analysis"). |

## What would reverse this decision

- **A measurement that the safe axes are too few.** If, for a fault, every
  decision-preserving axis yields exactly one instance, there is nothing to draw
  and decision 7 applies: exclude it rather than parameterise a draw that cannot
  vary.
- **Evidence that instances within a resolution are not interchangeable for
  dispatch.** If a program admitted on one instance cannot be expected to answer
  another instance of the same resolution, the resolution is not the right unit
  for the library and the state taxonomy needs splitting — a larger change that
  would supersede this ADR rather than amend it.
- **The build-time invariant proving too strict.** If legitimate draws routinely
  fail it, either the axis declaration or the decision rules are wrong; the
  declaration is what gets fixed, not the invariant.
- **A pair-level harness (#5) that reaches adequate state diversity without
  injector diversity.** That would remove the environment count as the binding
  constraint and lower this work's priority — though a new seed would still not be
  a new environment for the episode loop.
