# ADR-0021 — The harness keeps no bookkeeping in the clone

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It reverses spec revision 24's choice to keep `refs/sandbox/injected` on disk and revision 25's to keep `submodule-path` there, and narrows what `recorded_state_intact` checks.
- **Deciders:** repository owner

## Context

#103 moved the injected state's *name* and *values* out of the clone into
`Sandbox.recorded`, but left three refs behind under `refs/sandbox/`:

- `injected`, an empty marker so a second `inject` would refuse. Revision 24 kept it on
  disk because "an in-memory marker would not outlive its object".
- `submodule-path`, which the probes bind `{submodule_path}` from after a correct removal
  has deleted the `.gitmodules` entry.
- `refs-at-start`, the post-injection ref snapshot `tasks.invariants` checks against.
  Its "every `refs/sandbox/*` ref still resolves" clause doubled as the re-clone
  detector.

The first live run (#163) found the ReAct agent spending a turn on `git for-each-ref`
and `git cat-file -p refs/sandbox/*`. That made the cost visible, but cost was not the
main problem (#161):

- A precondition such as `git cat-file -e refs/sandbox/submodule-path` holds in every
  sandbox and in no real repository, so it would pass admission, which also runs in
  sandboxes.
- `refs-at-start` is a ready-made diff of what the injector moved.

## Decision

1. All three move into `Sandbox.recorded`: `"base"` is the double-injection marker,
   `RECORDED_SUBMODULE_PATH` holds the path, and `RECORDED_REFS_AT_START` holds the
   snapshot. Nothing is written under `refs/sandbox/` in either repository.
2. The in-memory marker is enough, which revision 24 doubted. A `Sandbox` is built only
   by `create`, never rebuilt from disk, so the record lives exactly as long as the
   sandbox it describes.
3. `submodule_path` takes the `Sandbox` rather than a path, and reads the record first
   and `.gitmodules` second, as before.
4. `recorded_state_intact` replaces "every `refs/sandbox/*` ref still resolves" with
   **every object a work ref named at the start is still in the object store**. A
   correct resolution moves refs but never deletes objects; a `reset --hard` leaves
   them in the store. A re-clone or a wipe loses them.

## Consequences

**Gained:** a precondition can no longer anchor on harness-only state, and the agent
cannot read the injection's ref diff. Issue #161's test, that no fault leaves anything
under `refs/sandbox/` in either repository, now holds for every fault.

**Accepted:** the re-clone detector is weaker for a fault whose every starting commit is
already on upstream. `dirty_tree` is the case today: a fresh clone of upstream still
holds every object the work refs named. There the fault's own checker catches the loss,
since the uncommitted work is gone, but `recorded_state_intact` alone does not.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| A sibling bare repository or a file under the sandbox root, outside the clone | Out of reach of git commands run from the work tree, but still on disk, where an agent with shell access can `cat ../...`. Memory is out of reach entirely, and nothing needs the record after the sandbox object is gone. |
| Keep the refs, and have admission refuse any program that names `refs/sandbox/` | #161's own weaker option. `for-each-ref` and `log --all` still reveal the refs, and the agent still pays to read them. |
| A harness nonce or the `.git` inode as the re-clone detector | Catches the `dirty_tree` case, but a nonce in the clone is readable bookkeeping again, and an inode is a platform-dependent heuristic. |

## What would reverse this decision

- A need to rebuild a `Sandbox` from disk, for example resuming a run after a crash.
  The record would then have to persist outside the clone, under the sandbox root but
  not inside `work`.
- A spec-gaming row that re-cloned a state whose commits were all on upstream and went
  uncaught by its fault's checker. The re-clone detector would then need a second
  signal.
