# ADR-0029 — Register the lock-conflict intent, so every fault is measured

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** narrows ADR-0019. Its motivating overlap state, `lockfile_conflict`'s,
  is no longer labelled by the sync intent, because the resolution that label named
  fails there. It also closes the spec's open risk 6: no fault's request is a fixed
  sentence any more, and `EXCLUDED_FROM_BENCHMARK` is empty.
- **Deciders:** repository owner. They approved registering the intent on #191 without
  a further sign-off. Recorded so each choice can be challenged.

## Context

`lockfile_conflict` returned one fixed request sentence, so it sat in
`EXCLUDED_FROM_BENCHMARK` (open risk 6, #25). #158 had also found `diverged`'s rules
labelling its state `merge`, so #191 asked first whether it is its own intent or more
`sync_fork_with_upstream` states.

**An experiment on #191 settled it.** Five fixed resolutions were run on three states
in throwaway repositories:

| state | plain `merge` | `take_upstream` | `keep_local` | union merge driver | delete markers |
| --- | --- | --- | --- | --- | --- |
| additions only | fails | **ok** | **ok** | fails | fails |
| upstream removed | fails | **ok** | fails | fails | fails |
| local removed | fails | fails | **ok** | fails | fails |

- **Every `diverged` resolution fails here, starting with a plain merge.** So it is its
  own intent, and `diverged` must refuse its states rather than label them.
- **The union merge driver keeps both sides' version lines.** That is a malformed lock,
  which the old three-clause checker passed.

The conversion took three steps that each left every measured number unchanged:

1. **The fingerprint observes three new facts**, read-only, by trying the three-way
   merge outside the repository: `merge_conflicted_files`, `upstream_dropped_lines` and
   `local_dropped_lines`.
2. **The injector selects one of three states**, and the checker gains two clauses: a
   removed dependency stays removed, and the file keeps exactly one `version` line.
3. **The intent is defined**, its acceptable sets pinned by replay, and `diverged`'s
   rules refuse a state where a sync would conflict
   (`StateFingerprint.sync_would_conflict`).

   That step changed one admission behaviour, recorded in spec revision 97. A
   `diverged` program whose preconditions accept the lock-conflict state is refused as
   firing on an unrelated state. ADR-0019 had judged it an overlap state where `merge`
   was correct, but a plain merge fails the fault's checker there. The gold merge
   program's `local_work_beyond_the_overlap` precondition keeps it off the state, and
   ADR-0019's overlap class stays in `admit` for any future overlap.

## Decision

1. **`INTENT` (`sync_through_a_conflicting_lockfile`) is registered.**
   `EXCLUDED_FROM_BENCHMARK` is empty. It is kept, with its test, so a future fault with
   a fixed sentence must be listed there or given an intent.
2. **`LOCKFILE_STATES` joins `STATE_GRID`.**
3. **`as_text` renders the three new fields** for every state.
4. **Tier 1 axes (ADR-0005):**
   - each side's package. The versions and the base version now follow from the
     drawn pair instead of being drawn on their own. Drawn independently, they
     multiplied the instance space until no tune or eval seed ever repeated an instance,
     and the cost curve is read from repeats.
   - `removal`, which side dropped the removable dependency. It separates the two states
     `take_upstream` covers, and does not vary for `keep_local`, which has one state.

   Instance identity is `lockfile_conflict/<resolution>/<axis>=<value>/...`.
5. **There are two resolutions over three states.**
   - `additions_only` accepts both, and is labelled `take_upstream`: upstream's file is
     the reference.
   - `upstream_removed` accepts only `take_upstream`.
   - `local_removed` accepts only `keep_local`.

## Consequences

**Accepted:**
- **Arm-2 numbers are not comparable across this change.** Every arm-2 text gains
  three more lines.
- **Fewer distinct environments than the seeds could give.** Deriving the versions from
  the package pair caps the family at 16 instances per state. The eval set builds 28,
  with 12 replays for the cost curve, rather than 40 with none.
- **The gold bodies are a stand-in for regeneration.** They rebuild the lock from one
  side's file plus the other side's additions, because the sandbox has no package
  manager. The fault's docstring has always said the file is lock-shaped, not a real
  lockfile.
- **Compiled `diverged` programs must stay off the lock-conflict state.** A live build's
  `diverged` program that accepts it is now refused at admission, where ADR-0019 let a
  `merge` or `rebase` program through. That is the correct verdict, because both fail
  there, but it may lower the build's admission count.
- **Two guard limits shaped the gold bodies.**
  - `runtime/guard.py` refuses a variable assigned by `while read` (the read is not at
    a statement start).
  - It treats a `/`-addressed `sed -i` script as an absolute path.

  The bodies avoid both. They are listed for the owner's review rather than changed
  here, because the guard is the safety boundary.
- **A conflict where both sides dropped lines has no label.** Neither resolution keeps
  both removals, so such a state is not injected. A real one would read as needing
  nothing.

**Gained:**
- **Every fault is measured.** The nominal 60-episode demo grid is the runnable one, and
  the eval set builds 119 environments.
- **The fault the module calls "the most interesting for the mismatch metric" is in
  the comparison**, with a checker that refuses both silent wrong fixes: dropping a
  dependency, and resurrecting one.

**New obligations:**
- Every intent that syncs commits must refuse `sync_would_conflict` states, as
  `diverged` now does.
- `tests/test_declared_state.py` expects an empty excluded set.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Model the states as more `sync_fork_with_upstream` states | Every `diverged` resolution fails on them, so the intent's labels would be wrong on every one, and its rules would have to grow a second, unrelated family inside them. |
| Accept the union merge driver as a resolution | It keeps both version lines. Accepting it would grade a malformed lock as a sync. |
| Detect a conflict with `git merge-tree --write-tree` | It writes objects into the repository, and `observe` must write nothing. A three-way `merge-file` on blobs copied outside the repository is read-only. |
| Run a real package manager for regeneration | The sandbox has none, and grading a regenerated real lockfile is a later change. The fault's docstring has said so since it was written. |

## What would reverse this decision

- A replay shows the checker accepting a resolution outside the declared set, or the
  reverse.
- A real lock-conflict state is common where both sides dropped lines. That state is
  unlabelled here, and it would need a resolution this intent does not have.
