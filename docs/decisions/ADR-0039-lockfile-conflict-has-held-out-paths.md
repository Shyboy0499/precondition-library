# ADR-0039 — `lockfile_conflict` has held-out paths, and the fingerprint reads paths with `-z`

- **Status:** accepted; decision 4 superseded by ADR-0046 (the gold programs find the file)
- **Date:** 2026-10-18
- **Supersedes:** nothing. It adds a third held-out source to the stage ADR-0033 registered,
  and corrects ADR-0038's audit count.
- **Deciders:** repository owner, issue #263.

## Context

ADR-0038's audit found 12 probes in `diverged` and `lockfile_conflict` programs that read git
paths in a way a space or a non-ASCII name could break. They were found by reading, because no
state either fault builds has such a path. Every shipped `lockfile_conflict` state keeps its file
at `deps.lock`, so a check that only works on that name passes admission and every
in-distribution pair.

## Decision

1. **`tasks.faults.lockfile_conflict` gains a held-out path axis** (`lock_path_for_seed`), drawn
   only at or above `HELD_OUT_SEED_BASE`. It is one of these four paths:
   - `services/api/deps.lock` (nested),
   - `web app/deps.lock` (a space),
   - `vendor/abhängigkeiten.lock` (non-ASCII),
   - `config/.deps.lock` (a dotfile).

   Each name keeps `lock` in it, so a program that recognises the file by name is not refused by
   the axis. Below the base every seed keeps `deps.lock` and its instance identity; above it, the
   identity carries `/path=…`. The checker grades the path the injector recorded, and the change
   surface is per seed. The 40 held-out seeds meet every path under both labels.
2. **`StateFingerprint.observe` reads every path list with `-z`**:
   - touched files,
   - dirty files,
   - untracked files,
   - upstream's tree.

   Building the non-ASCII state found ADR-0038's bug class in the harness itself:
   - `git diff --name-only` printed the name escaped;
   - the three-way read then found no such file;
   - so the conflict went unseen, and `build_sandbox` refused the state as mislabelled.

   The test that builds it fails without the fix.
3. **`bench.heldout.HELD_OUT_FAULTS` gains `lockfile_conflict`.**
4. **The gold `lockfile_conflict` programs require `deps.lock` on both sides.** Their bodies
   rebuild that file by name. On a held-out path every `git show <rev>:deps.lock` read nothing,
   so the removal checks held vacuously. On the held-out block the gold library made 40 fires, 15
   of them wrong: `take_upstream` on every `keep_local` state. Now it refuses all 40.

## What it found

On all three committed libraries (`results/heldout-2026-10-18/`), arm 3 mis-fired on 41 of its
101 held-out `lockfile_conflict` fires (13 of 33, 8 of 33, 20 of 35). It fired on none of the
fault-free negatives.

**Every wrong fire is on the spaced or the non-ASCII path.** Those two paths drew 60 fires, 41
of them wrong. On the nested and dotfile paths arm 3 made 41 fires, none wrong.

Four probes cause all 41. For one held-out state of each program and path, a shipped seed builds
the same instance at `deps.lock`. On those pairs exactly one precondition goes from refusing on
the shipped state to holding on the held-out one, and it is the probe below:

| library | program | flipped precondition | how the path breaks it | wrong fires |
| --- | --- | --- | --- | --- |
| replicate 1 | `lockfile_conflict` take-upstream | `local_dropped_no_upstream_kept_lines` | `for f in $(…)` splits `web app/deps.lock` | 3 (space) |
| replicate 1 | `diverged` discard | `local_commits_touch_no_path_upstream_carries` | `git cat-file -e rev:$p` on the escaped name | 10 (non-ASCII) |
| replicate 2 | `lockfile_conflict` take-upstream | `local_removals_not_revived` | `for f in $(…)` and `git show "$b:$f"` | 8 (3 space, 5 non-ASCII) |
| replicate 3 | `diverged` discard | `local_commits_carry_nothing_new` | an unquoted `-- $files` pathspec | 20 (both) |

Two of the four are `diverged` programs firing `discard` on a lock-file conflict. Discarding the
local commits loses the local side's dependency changes. Each of the four failing checks is an
"absence" check, one that should refuse when a path is shared. On a path it cannot read, it
finds nothing, so it holds.

ADR-0038's audit, done by reading, listed three of the four probes. It missed replicate 3's
`local_commits_carry_nothing_new`, because the audit looked for `comm`, `while read` and
`for … in`, not an unquoted path list. That audit's count is therefore **at least 16 probes in 10
of the 40 admitted programs**, not 15 in 9. Reading is not a complete audit; this block is a
partial measured one.

## Consequences

**Accepted:**
- **The axis is still a path axis.** It moves one file and keeps the state's kind.
- **No comparison with arm 2.** There is no held-out floor, so this block may not say arm 3
  beats arm 2 (ADR-0033). Arm 2 mis-fired on 29 of 31, 32 of 32 and 25 of 32 at matched
  coverage, and that is reported only beside arm 3's figures.
- **Other committed figures move slightly.** Six held-out `dirty_tree` fingerprints change: the
  ones whose tracked file is `design/Übersicht.md`, which now prints as its name. Their committed
  results were regenerated:
  - arm 3's fires and mis-fires, and arm 2 at the matched point, are unchanged;
  - arm 2's curve moved at a few other thresholds.

  No shipped fingerprint moved: 410 compared, across every fault at seeds 0–39 and 2000–2039,
  plus ten fault-free seeds. Of the 200 held-out fingerprints compared, only those six moved.

**Gained:** the first held-out source on which arm 3 fails often, not rarely. It confirms by
running what ADR-0038 found by reading, and it shows the failure is not confined to one program.

**New obligations:** a fault's held-out axis must leave every seed below the base on its
shipped draw and identity (`tests/test_heldout_states.py` pins it for this fault).

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Rename the file but keep it in the root | It tests a name, not a path: a probe that splits on `/` or a directory with a space is never exercised. |
| A name without `lock` in it | A program that finds the file by a `lock` pattern would abstain, and the block would measure the pattern, not path handling. |
| Leave the fingerprint as it was, and draw no non-ASCII path | That would hide a harness defect, and miss two of the four failing probes. |
| Rewrite the gold bodies to find the file | It changes the reference's behaviour on shipped states; requiring the file keeps it identical there and makes it refuse elsewhere. |

## What would reverse this decision

A held-out `lockfile_conflict` state whose label, read by the rule, disagrees with the seed's
declared resolution. Every held-out seed is built with that check, and the four paths' states
are built in tests.
