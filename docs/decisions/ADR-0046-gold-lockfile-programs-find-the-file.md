# ADR-0046 — The gold `lockfile_conflict` programs find the conflicted file

- **Status:** accepted
- **Date:** 2026-10-24
- **Supersedes:** ADR-0039 decision 4, which had the gold programs require `deps.lock` and so
  refuse every other path. ADR-0039's alternative "rewrite the gold bodies to find the file" is
  the one taken here.
- **Deciders:** repository owner ("that's fine if we reverse a couple of the decisions").

## Context

ADR-0039 made the gold lock-file programs require `deps.lock` on both sides. Named by path, their
`git show <rev>:deps.lock` read nothing on a held-out path, the removal checks held vacuously, and
`take_upstream` fired on every held-out `keep_local` state. Requiring the file fixed that by
refusing. The cost showed in the gold sweep (ADR-0045, amended): no gold applies to held-out
`lockfile_conflict`, so the lock-file grader goes unchecked on exactly the paths that broke the
learned programs.

ADR-0039 rejected finding the file on the ground that it "changes the reference's behaviour on
shipped states".

## Decision

1. **The gold programs find the file.** It is the one path a merge of upstream would leave
   conflicted, read with `git merge-tree --write-tree --name-only -z`, which writes nothing, so
   the probes stay read-only.
2. **A new first precondition replaces the `deps.lock` one.** A merge must conflict in exactly
   one file, and that file must be lock-shaped on both sides (a `packages = [` line).
3. **Every probe and the body read that path, quoted.** `web app/deps.lock` and
   `vendor/abhängigkeiten.lock` are read whole.
4. **The marker postcondition reads git's start and end markers in tracked files**, as the
   checker does since ADR-0045, rather than any `=======` line in `deps.lock`.

## What it found

- **Shipped states are unchanged.** On all 232 shipped (seed, resolution) combinations (seeds
  0–59, the tune and eval blocks), the old and new programs agree on whether they fire, on whether
  the replay succeeds and on the tree it leaves.
- **Held-out states are now covered.** At every held-out path and both resolutions, only the
  state's own program fires.
- **The gold sweep grades all 40 held-out lock-file states, with no defect.** That brings the
  held-out sweep to 240 graded, the same as eval and real-host.
- **The CI sample now catches all four ADR-0045 defects.** With the committed diff read without
  `-z`, gold's replays on the held-out lock-file states fail (3002, 3006, 3038). Before this,
  nothing in the sample committed to a quoted path.

## Consequences

**Accepted:** the gold programs depend on `git merge-tree --write-tree`, available since git 2.38.

**Gained:** the lock-file grader is checked on held-out paths by the sweep and in CI. The
reference now resolves states that the learned programs mis-handle, which is what a reference is
for.

**New obligations:** none.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Keep requiring `deps.lock` | It leaves the grader unchecked where the learned programs broke. |
| Bind the lock path as a parameter | No such parameter exists in the vocabulary, and a checkout would have nothing to bind it from; the conflict itself names the file. |

## What would reverse this decision

A shipped state on which the old and new programs differ.
