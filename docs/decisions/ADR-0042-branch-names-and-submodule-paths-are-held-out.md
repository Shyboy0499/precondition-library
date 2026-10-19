# ADR-0042 — `branch_renamed` and `submodule_moved` have held-out axes

- **Status:** accepted
- **Date:** 2026-10-19
- **Supersedes:** nothing. It adds the last two git faults to the held-out stage ADR-0033
  registered.
- **Deciders:** repository owner, issue #263.

## Context

ADR-0033, ADR-0037 and ADR-0039 gave held-out axes to `dirty_tree`, `diverged` and
`lockfile_conflict`. The lock-file block broke arm 3 on 41 of 101 fires, all on paths with a
space or a non-ASCII name. `branch_renamed` and `submodule_moved` had no held-out axis, so
nothing showed whether their programs were tied to the names the generator always uses:
`trunk`, `develop`, `default` and `primary` for a renamed branch, and `vendor/libcore` for the
submodule.

## Decision

1. **`branch_renamed` draws a held-out name above `HELD_OUT_SEED_BASE`**
   (`renamed_branch_for_seed`): `release/2026`, `main-v2`, `stable.next` or
   `team/integration`. Two contain a `/`, so a probe that splits `upstream/<name>` on the last
   `/` breaks while one that strips the remote prefix does not. The name is already a Tier 1
   axis and part of the identity, so held-out identities differ without a suffix.
2. **`submodule_moved` puts the submodule at a held-out path above the base**
   (`submodule_path_for_seed`): `third_party/libs/core`, `.deps/libcore`, `lib/core-v2` or
   `ext/libcore`.
   - The injector, its helpers and the checker take the seed's path. The checker reads it
     from `Sandbox.recorded`, the same record `{submodule_path}` binds from.
   - The change surface is per seed.
   - A held-out identity carries `/path=…`.
3. **Every held-out value is shell-safe** (ADR-0040), so it binds. An unsafe value would be
   left unbound and every program needing it would refuse, which measures the binding screen,
   not the programs.
4. **Below the base nothing moves.** All 3,000 seeds keep their shipped name, path and
   identity. All 80 held-out states were built with the label check on. The 40 held-out seeds
   meet every name and path under every resolution.
5. **`bench.heldout.HELD_OUT_FAULTS` covers all five git faults.**

## What it found

On all three committed libraries arm 3 fired on all 40 held-out positives of each block,
240 fires, none wrong, and on none of the fault-free negatives (`results/heldout-2026-10-19/`).
An independent recount agrees per name and per path.

None of the 20 compiled programs for these faults names a branch or a submodule path. Every one
binds `{upstream_branch}` or `{submodule_path}`. Together with the lock-file block, the
held-out stage so far shows:

| how a program gets the varied value | held-out fires | wrong |
| --- | ---: | ---: |
| as a bound parameter (branch names, submodule paths) | 240 | 0 |
| from git's printed path lists, plain names (`dirty_tree`, lock file nested or dotfile) | 131 | 0 |
| from git's printed path lists, a space or a non-ASCII name | 90 | 42 |
| a new shape, not a new name (`diverged`) | 120 | 0 |

`dirty_tree`'s 120 fires are split by state: the 30 states whose path set holds a space and a
non-ASCII name, with the block's 1 wrong fire, sit in the third row; the other 90 in the second.
The four rows sum to the 581 held-out fires across all five blocks. The table is a description of these libraries, not a claim about compiled programs in
general.

## Consequences

**Accepted:** both axes vary a name, not the kind of state. A real repository's branch and
submodule names are also usually safe, so this block says little about the cases ADR-0040
refuses.

**Gained:** every git fault now has a held-out axis, and the stage's results separate cleanly
by how a program gets the value that varies.

**New obligations:** none beyond ADR-0033's: a held-out axis keeps every seed below the base on
its shipped draw, pinned per fault in `tests/test_heldout_states.py`.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Branch names or submodule paths with spaces | They are left unbound by ADR-0040, so every program refuses: the block would measure the screen. |
| A second submodule beside the first | It changes the state's kind, since the rules read one submodule, and could relabel. |
| Draw held-out names from the shipped pool's style (`trunk2`) | It would not exercise the `/` that a name-parsing probe gets wrong. |

## What would reverse this decision

A held-out state whose label, read by the rule, disagrees with the seed's declared resolution.
Every held-out seed is built with that check.
