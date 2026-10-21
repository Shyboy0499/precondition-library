# ADR-0045 — Four grader defects found by replaying held-out and real-host fires

- **Status:** accepted
- **Date:** 2026-10-21
- **Supersedes:** nothing. It corrects four graders; no registered metric or figure moves.
- **Deciders:** repository owner (asked to keep implementing).

## Context

ADR-0044 replays each dispatch fire and grades what it leaves. On the eval states every grade
was plausible. Replaying the fires of the held-out stage (ADR-0033) and of the real-host stage
(ADR-0043) was the first time the graders met file names that need quoting and real projects'
files. Each defect below turned a correct resolution into a refusal. Each was found because a
replay that had evidently worked was graded as failing, and confirmed by rebuilding the state
by hand.

## Decision

1. **`recorded_state_intact` reads the committed diff with `-z`.**
   - Without it, git escaped `vendor/abhängigkeiten.lock` as `"vendor/abh\303\244ngigkeiten.lock"`.
   - A commit to the very file the fault allows was then graded as outside its change surface,
     which read as "lost recorded state".
2. **The `lockfile_conflict` checker matches git's start, end and base markers only.**
   - It matched any line starting with seven `=`.
   - Every real-host state has a `HISTORY.md` or `README` heading underlined with `=`, so every
     correct resolution there was refused.
   - The separator only ever stands between a start and an end marker, so dropping it misses no
     leftover conflict.
3. **The `dirty_tree` checker requires the work's file to hold the appended text.**
   - It reverse-applied the recorded patch. That patch's hunk starts at line 1, and `git apply`
     pins such a hunk to the top of the file.
   - On a held-out state whose upstream prepends a line to the same file, a stash-and-restore
     that kept the work intact was graded as discarding it.
   - The injector now records the file and the text it appends.
4. **The gold `aside` program walks git's `-z` lists, and the guard knows `read -d ''`.**
   - The gold body split `scratch notes.md` in an unquoted loop, so its stash could not be
     restored.
   - The rewritten loop needs `read -r -d ''`. The guard did not recognise a `read` option that
     takes an argument, so it refused the name that read assigns. It now skips the argument.
   - All 605 committed and gold bodies keep their guard verdicts.

## What it found

**Before and after.**
- Before the fixes, the real-host replays graded 27 of run 11's and 43 of run 13's correct
  arm-3 fires as not fixed. The heading underline alone accounts for 27 and 16 of them; the rest
  are run 13's two failing programs.
- Before the fixes, the held-out replays graded 10 of run 11's fires as "lost recorded state",
  all from the quoted non-ASCII path. The `dirty_tree` check also refused 13 of run 11's and 13
  of run 12's correct stash fires, whose work was intact.
- After them, on the eval block, the real-host replays agree with the synthetic ones on every
  (arm, pair, program, outcome) row.
- On the held-out block every remaining refusal is a program's, as each rebuilt case shows.

**What the fixes do not move.**
- Re-running the eval replays (ADR-0044) on the fixed code reproduces the committed files byte
  for byte.
- Every hand-written gold program passes on all 414 real-host states where its resolution is
  accepted. Gold `lockfile_conflict` programs still fail on held-out paths, because they require
  `deps.lock` by design.

## Consequences

**Accepted:** the graders were tested on the generator's states only. Below the held-out base
the generator never writes:
- a path needing quoting;
- a heading underline;
- a work file so short that the work's hunk starts at line 1.

The shipped `same_file` state also has upstream edit the top of the work's file, but `app.py`
is long enough that the hunk starts lower down. Any episode graded before this on such a state was graded by the defective clause. No
committed episode result was built on one: the live builds used the shipped seeds.

**Gained:** a check that a grader refuses only what is wrong. The gold sweep (every gold program,
every state it is accepted on) found the fourth defect, and is cheap to run again.

**New obligations:** a new state source -- held-out axis, host, family -- is not trusted until
gold passes on it. A gold refusal there is a grader or gold defect until shown otherwise.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Keep the patch check and add context to the recorded patch | It still fails when upstream edits inside the context. The appended text is what "the work survives" means. |
| Exclude real hosts' doc files from the marker scan | A leftover conflict can be in any file; the start and end markers are what identify one. |
| Report the refusals as program failures | Each was rebuilt and checked by hand; the work or the merge was intact. |

## What would reverse this decision

A leftover conflict, or a discarded work, that the corrected graders pass. Each fix has a test
that its negative case is still refused.
