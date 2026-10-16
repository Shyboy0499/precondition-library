# ADR-0037 — `diverged` has a held-out shape axis

- **Status:** accepted
- **Date:** 2026-10-16
- **Supersedes:** nothing. It adds a second held-out source to the stage ADR-0033 registered.
- **Deciders:** repository owner, issue #263 part 2.

## Context

ADR-0033's first held-out source varies `dirty_tree`'s **paths** and nothing else. Every held-out
state there has the shipped shape, so it asks whether a program's checks survive new names, not
whether they survive a state built differently. ADR-0033 named "held-out axes in the other four
faults" as the next stage.

Every shipped `diverged` state shares one shape: upstream exactly one commit ahead, touching one
file (`app.py`), and 1–3 local-only commits. A probe that reads `git rev-list --count` or
`git diff --name-only` sees the same numbers and lists on every shipped state. A program can
therefore be admitted with a check that only works on that shape, and nothing in the build or the
primary metric would show it.

## Decision

1. **`tasks.faults.diverged` gains a shape axis drawn only at or above `HELD_OUT_SEED_BASE`**
   (`shape_for_seed`). A held-out seed builds 2–3 upstream commits, an upstream-only file beside
   `app.py` (one of `config/settings.toml`, `CHANGELOG.md`, `notes/upstream.md`), and 4–5 local
   commits. Below the base the shape is the shipped one: one upstream commit, no extra file, the
   drawn 1–3 local commits. All 3,000 seeds below the base were checked to keep their instance
   identity unchanged.
2. **Labels are invariant by construction.** The rule reads which files each side touched and
   whether they overlap (`conflicting_files`). The extra upstream commits touch only the
   upstream-only file, which overlaps nothing, so `discard`, `rebase` and `merge` keep their
   states. All 40 held-out seeds were built and labelled by the fault's own rule: 0 relabelled,
   0 that a sync would conflict on.
3. **The identity carries the shape only when held out** (`/shape=up{n}+{file}`), so the instance
   counts the committed figures were taken over do not move.
4. **The change surface is per seed** (`change_surface_for_seed`, ADR-0033's per-seed hook): a held-out
   seed's surface adds its upstream-only file, which a merge or rebase carries into the committed
   diff. A shipped seed's surface is unchanged.
5. **`bench.heldout.HELD_OUT_FAULTS` is `("dirty_tree", "diverged")`.** Each fault's block is read
   on its own (`--faults`), as part 1's was.

## Consequences

**Accepted:** the axis is one fault's, and it keeps the state's kind: more commits and files, not a
different situation. It is a shape test, not a real-repository test.

**Gained:** a held-out source that changes what git reports about the state, not just the names in
it. On all three committed libraries arm 3 fired on all 40 held-out `diverged` states with 0
wrong (`results/heldout-2026-10-16/`).

**New obligations:** a fault's held-out axis must keep every seed below the base on its shipped
draw, and the stage's tests pin that per fault (`HELD_OUT_AXES`).

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Extra upstream commits that edit `app.py` | They can collide with the local insertion and make the sync conflict, which takes the state out of `diverged`'s rule entirely (`sync_would_conflict`). |
| A merge commit in the local history | It changes what `rebase` does to the history, so its label would need a decision of its own. |
| Varying which file each side edits | ADR-0005 left it out as Tier 2, because it can move `rebase` into `merge`. A held-out axis must not relabel. |

## What would reverse this decision

A held-out `diverged` state whose label, read by the rule, disagrees with the seed's declared
resolution. The test pins one held-out state's label, and the build check above found none in 40.
