# Held-out states, part 3: `lockfile_conflict` at held-out paths, 2026-10-18

Parts 1 and 2 (`results/heldout-2026-10-10/`, `results/heldout-2026-10-16/`) read two held-out
sources: `dirty_tree` at held-out paths and `diverged` in a held-out shape. Arm 3 mis-fired once
in 240 fires there. ADR-0038's audit then found probes in `diverged` and `lockfile_conflict`
programs that read git paths in a way a space or a non-ASCII name breaks. No state either fault
built had such a path, so those probes had not been run on one.

This block gives `lockfile_conflict` a held-out path axis (ADR-0039). Above `HELD_OUT_SEED_BASE`
the lock-shaped file is kept at one of four paths:

- `services/api/deps.lock` (nested),
- `web app/deps.lock` (a space),
- `vendor/abhängigkeiten.lock` (non-ASCII),
- `config/.deps.lock` (a dotfile).

Nothing else about the state changes, and every label is kept.

No model call, no rebuild: each committed frozen library is read-only, with its digest compared
before and after. Code: the commit that adds this directory.

```bash
python -m precondition_library.bench.heldout --run results/replicates-2026-10-05/run-N \
  --faults lockfile_conflict --out results/heldout-2026-10-18/lockfile_conflict/run-N
```

## Result

Seeds 3000–3039, uninformed regime, the lexical arm 2. The block is 40 held-out positive states
and 40 fault-free negatives, 37 distinct instances.

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| arm 3: fires, mis-fires | 33, **13** | 33, **8** | 35, **20** |
| `services/api/deps.lock` (nested): fires, mis-fires | 6, 0 | 6, 0 | 8, 0 |
| `web app/deps.lock` (space): fires, mis-fires | 10, 3 | 10, 3 | 10, 10 |
| `vendor/abhängigkeiten.lock` (non-ASCII): fires, mis-fires | 10, 10 | 10, 5 | 10, 10 |
| `config/.deps.lock` (dotfile): fires, mis-fires | 7, 0 | 7, 0 | 7, 0 |
| fires on the 40 fault-free negatives | 0 | 0 | 0 |
| arm 2 at arm 3's coverage: mis-fires | 29/31 | 32/32 | 25/32 |

Every count was re-derived through a second path: each state built again and matched directly,
with the fired program checked against the fault's own acceptable resolutions. The second path
agrees on all three libraries, per path. Running the stage again from the committed code
reproduces every file in this directory byte for byte.

## What broke

Over the three libraries arm 3 made 101 fires and 41 were wrong. **All 41 are on the spaced or the
non-ASCII path**, which drew 60 fires; the nested and dotfile paths drew 41 fires and none was
wrong.

Four probes cause all of them. For one held-out state of each program and path, a shipped seed
builds the same instance at `deps.lock`. On those pairs, exactly one precondition goes from
refusing on the shipped state to holding on the held-out one:

| library | program fired | precondition that flipped | why the path breaks it | wrong |
| --- | --- | --- | --- | --- |
| run-11 | `lockfile_conflict` take-upstream | `local_dropped_no_upstream_kept_lines` | `for f in $(…)` splits `web app/deps.lock` in two | 3 |
| run-11 | `diverged` discard | `local_commits_touch_no_path_upstream_carries` | `git cat-file -e rev:$p` on the escaped name | 10 |
| run-12 | `lockfile_conflict` take-upstream | `local_removals_not_revived` | `for f in $(…)` and `git show "$b:$f"` | 8 |
| run-13 | `diverged` discard | `local_commits_carry_nothing_new` | an unquoted `-- $files` pathspec | 20 |

**The checks fail in the dangerous direction.** Each is an absence check: it should refuse when
a path is shared or a line was dropped. On a path it cannot read, it finds nothing, and holds.
Two of the four fire `discard` on a lock-file conflict, which throws the local side's dependency
changes away.

ADR-0038's audit, done by reading, listed three of these four. It missed run-13's
`local_commits_carry_nothing_new`, so its count is at least 16 probes in 10 of the 40 admitted
programs.

## Found on the way

- **The fingerprint had the same bug.** `StateFingerprint.observe` read `git diff --name-only`
  without `-z`. On the non-ASCII path it saw an escaped name, found no such file, and missed the
  conflict, so the build refused the state as mislabelled. It now reads every path list with
  `-z`.
  - Of the 610 fingerprints compared before and after, only six held-out `dirty_tree` states
    changed: the ones whose tracked file is `design/Übersicht.md`.
  - Those committed results in parts 1 and 2 were regenerated. Arm 3's counts and arm 2 at the
    matched point did not move; arm 2's curve moved at a few other thresholds.
- **The gold programs had a hard-coded name.** The hand-written `lockfile_conflict` resolutions
  read `deps.lock` by name. On a held-out path their removal checks held vacuously, so
  `take_upstream` fired on all 15 held-out `keep_local` states. They now require `deps.lock` on
  both sides, and refuse all 40 held-out states.

## What it shows

- **Held-out paths can break arm 3 badly.** On the two awkward paths, 41 of 60 fires were wrong.
  The in-distribution 0 of 563, and parts 1 and 2's 1 of 240, did not predict this: the probes
  are right on every name the generator uses.
- **The failure is the bug class ADR-0038 named.** All four probes read a path list without `-z`,
  then used it as a file name, a pathspec, or split it on spaces.
- **Plain held-out paths carried.** Nested directories and a dotfile cost no correctness. Arm 3
  fired on 13, 13 and 15 of those 20 states, against 27, 27 and 29 of the 40 in-distribution
  `lockfile_conflict` positives (`results/hybrid-2026-10-11/run-N/lexical/pairs.jsonl`).

## What it does not show

- **A comparison with arm 2.** No held-out floor is measured, so no sentence may say arm 3 beats
  text similarity here (ADR-0033). Arm 2's mis-fires are reported beside arm 3's, not against
  them.
- **Whether ADR-0038's prompt rule prevents this.** These libraries were compiled before the rule
  existed. A live build would show it.
- **How often real repositories have such paths.** That depends on the repositories, not on this
  block.
