# ADR-0038 — The compile prompt says how git quotes paths

- **Status:** accepted
- **Date:** 2026-10-17
- **Supersedes:** nothing. It adds one rule to the compile prompt.
- **Corrected by:** ADR-0039. Running the probes on held-out `lockfile_conflict` paths found a
  fourth failing one this audit missed, so its count is at least 16 probes in 10 programs.
- **Deciders:** repository owner, issue #263 part 2.

## Context

Arm 3's first mis-fire came from the held-out stage (`results/heldout-2026-10-16/`). Replicate 3's
`stash` program fired on seed 3038, a `collision` state whose untracked `scratch notes.md` upstream
also adds. Its precondition `no_untracked_collision_with_incoming` compares the untracked files from
`git status --porcelain` with the incoming files from `git diff --name-only`.

Git does not print paths in one way:

| command | `scratch notes.md` | `café.md` |
| --- | --- | --- |
| `git status --porcelain` | `"scratch notes.md"` | `"caf\303\251.md"` |
| `git status --porcelain` with `core.quotePath=false` | `"scratch notes.md"` | `café.md` |
| `git diff --name-only`, `git ls-files`, `git ls-tree --name-only` | `scratch notes.md` | `"caf\303\251.md"` |
| any of them with `-z` | `scratch notes.md` | `café.md` |

The table is git 2.43's output in a scratch repository. `core.quotePath=false` is not a fix,
because `status` still quotes a space.

An audit of the three committed libraries covered every admitted probe that reads a git path
list. The `dirty_tree` collision checks are the probes whose input a held-out state varies. All 10
such preconditions were run on scratch repositories with a colliding path that is plain, spaced or
non-ASCII. The path was either an untracked file upstream adds, or a tracked file both sides edit.
Three break, in two programs, and `tests/test_path_quoting.py` keeps the untracked-file cases as
controls:

- **Replicate 3's `stash` program** has two probes, one for untracked files and one for modified
  files. Each compares `status` output with `diff` output. Both break on a path with a space. Both
  escape a non-ASCII name the same way, so they still match on one.
- **Replicate 1's `commit` program** reads `diff --name-only` and tests each printed name with
  `[ -e "$p" ]`. A space prints bare, so that case works. An escaped non-ASCII name is not a file,
  so a colliding `café.md` goes unseen. No held-out state exposes this: the pool's only non-ASCII
  path is a tracked file, never the colliding one.

The other seven compare `ls-files`, `diff` and `ls-tree` output with each other. All three escape
alike, so each of those gave the same answer on all three paths.

The listing also found 12 more probes, found by reading, not by running: one `dirty_tree`
postcondition, and the rest in `diverged` and `lockfile_conflict` programs. Each passes a printed
path to `git show "$rev:$f"`, `git cat-file -e`, `git diff -- "$f"` or `git ls-files
--error-unmatch`, or splits a path list with `for f in $(…)`:

- replicate 1: `dirty_tree` aside's `sidecar_preserved`, `diverged` discard's
  `local_commits_touch_no_path_upstream_carries`, and `lockfile_conflict` take-upstream's
  `local_dropped_no_upstream_kept_lines`;
- replicate 2: four preconditions and two postconditions of the two `lockfile_conflict` programs;
- replicate 3: three preconditions of the two `lockfile_conflict` programs.

None of the 12 has been run on a path that would break it, and no shipped or held-out state gives
one such a path. Counting both kinds, 15 probes in 9 of the 40 admitted programs read paths in a
way that a space or a non-ASCII name could break.

Each probe is right on every shipped state, because no shipped path needs quoting. So admission
passed each one, and the in-distribution metric could not see the problem. The model was never told
that git quotes paths.

## Decision

1. **The compile prompt gains a rule** after the absence rule. It names which commands quote what,
   and says that comparing two path lists or testing a printed path as a file is wrong on the paths
   a test repository lacks. It also says to read every path list with `-z` and turn the NULs into
   newlines, and to list untracked files with `git ls-files --others --exclude-standard -z` rather
   than by parsing `git status`. It shows the collision check written that way, as a block scalar.
2. **The rule is pinned by what git does, not only by its wording** (`tests/test_path_quoting.py`):
   - The tests read the example probe out of the prompt as YAML and run it against real
     repositories, on a plain, a spaced and a non-ASCII colliding path. On each it must see the
     collision, and it must hold when the untracked file lies elsewhere.
   - It is also run through `evaluate_predicates` on held-out states 3038 and 3010. On 3038 it
     refuses; there, replicate 3's probe fires.
   - The two audited probes are kept as controls. Each must be right on the shipped path and wrong
     on its own quoted path.
3. **The committed libraries are not rebuilt**, and no figure moves. The rule changes future
   compiles only. Whether it removes the defect from compiled programs is a question for the next
   live build, and needs an API key.

## Consequences

**Accepted:** this is a prompt rule. A model can still ignore it, and the gate still cannot catch a
probe that is wrong only on paths its states never use. The rule also lengthens every compile
prompt by 865 characters, identically across arms. So admission rates for builds made with
it are not comparable to those made without it, as with spec revisions 110, 111 and 118.

**Gained:** the bug class the held-out stage found is named where programs are written, and the
idiom the prompt recommends has been run on the paths that broke the admitted probes.

**New obligations:** none for admission. The 12 probes found only by reading stay unverified until
a held-out axis gives `diverged` or `lockfile_conflict` an awkward path. A future held-out path
pool that adds a colliding non-ASCII untracked path would expose replicate 1's probe. Adding one
would change which state the existing held-out seeds draw, so it would need a seed block of its
own.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Admission also builds states with spaced and non-ASCII paths | It would move the held-out axis into the gate, so the held-out stage would stop measuring generalisation and start measuring the training set. A path pool for admission would need its own decision. |
| A static check that refuses `git status --porcelain` without `-z` in a probe | Many correct probes read `status` only for whether it prints anything (`test -n "$(git status --porcelain)"`). Telling those from a path comparison means parsing shell, and replicate 1's defect uses no `status` at all. |
| Run every probe with `-c core.quotePath=false` | It does not stop `status` quoting a space, which was the mis-fire. It also changes what the agent and the bodies see. |
| Rewrite the audited probes in the committed libraries | The libraries are frozen evidence. Editing them would make the committed figures describe programs nobody compiled. |

## What would reverse this decision

A live build made with the rule whose admitted probes still read paths without `-z` about as
often as the committed libraries' do (15 probes in 9 of 40 admitted programs). The rule would then
cost prompt length for nothing, and only a gate-side check would help.
