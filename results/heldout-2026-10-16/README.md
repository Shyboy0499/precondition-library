# Held-out states, part 2: all three libraries, and a held-out *shape*, 2026-10-16

Part 1 (`results/heldout-2026-10-10/`, #269) measured one held-out source on replicate 2's library:
`dirty_tree` states that write paths no shipped seed draws. This adds two things:

1. **The same `dirty_tree` block on replicates 1 and 3**, so the source is read on all three
   committed libraries.
2. **A second fault whose held-out states change *shape*, not just names (ADR-0037).** Every
   shipped `diverged` state has upstream exactly one commit ahead, touching one file (`app.py`),
   and 1–3 local commits. A held-out seed builds 2–3 upstream commits, an upstream-only file
   beside `app.py` (`config/settings.toml`, `CHANGELOG.md` or `notes/upstream.md`), and 4–5
   local commits. Every label is kept: the rule reads which files each side touched and whether
   they overlap, and an upstream-only file overlaps nothing. What changes is exactly what a probe
   reading `rev-list --count` or `diff --name-only` sees.

No model call, no rebuild: each committed frozen library is read-only, its digest compared before
and after.

```bash
python -m precondition_library.bench.heldout --run results/replicates-2026-10-05/run-N \
  --faults dirty_tree --out results/heldout-2026-10-16/dirty_tree/run-N
python -m precondition_library.bench.heldout --run results/replicates-2026-10-05/run-N \
  --faults diverged --out results/heldout-2026-10-16/diverged/run-N
```

## Result

Seeds 3000–3039, uninformed regime, the lexical arm 2. Each fault's block is 40 held-out positive
states and 40 fault-free negatives.

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| `dirty_tree`, held-out paths: arm 3 fires, wrong | 40, 0 | 40, 0 (part 1) | 40, **1** |
| `diverged`, held-out shape: arm 3 fires, wrong | 40, 0 | 40, 0 | 40, 0 |
| fires on the 40 fault-free negatives (each fault) | 0 | 0 | 0 |
| distinct instances (`dirty_tree` / `diverged`) | 31 / 35 | 31 / 35 | 31 / 35 |

Every count was re-derived through a second path: each state built again and matched directly,
with the fired program checked against the fault's own acceptable resolutions. The second path
agrees on all six.

## The first arm 3 mis-fire

Replicate 3's library fired `stash` on seed 3038, a `collision` state that needs `aside`. Its
untracked file is `scratch notes.md`, which upstream also adds.

The `stash` program's precondition `no_untracked_collision_with_incoming` compares two git outputs:

```sh
! comm -12 <(git status --porcelain --untracked-files=all | sed -n 's/^?? //p' | sort) \
           <(git diff --name-only HEAD..{upstream_remote}/{upstream_branch} | sort) | grep -q .
```

`git status --porcelain` prints a path containing a space in quotes (`?? "scratch notes.md"`), and
`git diff --name-only` prints it bare. The two lists never meet, so the check reports no collision
and the program fires. That is confirmed in a scratch repository with the same two commands. Stash
on a colliding untracked file is exactly the case the `aside` resolution exists for.

**This is the generalisation failure #263 asks about.** The probe is correct on every shipped
state, because no shipped path contains a space, so the gate admitted it and the in-distribution
metric could never see it. On held-out paths it mis-fires once in 40.

## What it shows

- **The shape axis carries.** On all three libraries arm 3 fired on every held-out `diverged`
  state, correctly, though upstream is now 2–3 commits ahead across two files and the local side
  has more commits than any shipped seed draws. No program's checks were tied to those counts.
- **The path axis does not always carry.** Replicate 3's `stash` program reads paths in a way that
  breaks on a path with a space. Held-out mis-fires: 1 of 240 fires over both sources and three
  libraries (0.4%, 95% Wilson upper bound 2.3%). In-distribution it was 0 of 563.
- **Why it can happen.** A precondition is learned on, and admitted against, the generator's
  states. A probe that is wrong only outside them passes every check the gate runs.

## What it does not show

- **A comparison with arm 2.** As in part 1, arm 3 decided nearly every pair correctly, so the
  registered rule reports no comparison, and no held-out floor is measured (ADR-0033). These are
  arm 3's own rates.
- **States of a different kind.** Both sources keep the fault's states recognisable: new paths, new
  counts. Real checkouts (#181) and other faults' axes remain.
- **How often a space-in-path probe defect would bite in practice.** That depends on the
  repositories, not on this block.

## Regenerated on 2026-10-18 (ADR-0039)

`StateFingerprint.observe` now reads git path lists with `-z`. Before, a non-ASCII name such as
`design/Übersicht.md` was printed as an escaped string in the fingerprint arm 2 reads. The held-out
`dirty_tree` directories here were regenerated with the fixed fingerprint:

- arm 3's fires and mis-fires are unchanged;
- arm 2 at the matched point is unchanged;
- arm 2's curve moved at a few other thresholds.

Every figure quoted in this README stands.
