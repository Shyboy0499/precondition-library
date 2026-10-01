# ADR-0013 — The unprivileged user and the disk quota are a runner requirement, not library code

- **Status:** accepted (2026-10-01)
- **Date:** 2026-10-01
- **Supersedes:** nothing (closes the last two items of issue #10's "replay runs as an unprivileged user with no network, ulimits, a disk quota, and the process group killed on timeout")
- **Deciders:** repository owner

## Context

Issue #10 asks that unattended replay run "as an unprivileged user with no
network, ulimits, a disk quota, and the process group killed on timeout". Four of
those five are now enforced from library code, each where a process can do it to
itself:

- the **process group is killed on timeout**, and bodies and probes run under
  POSIX **`RLIMIT_FSIZE`** (256 MiB) and `RLIMIT_CORE` 0 (`runtime.confine`,
  revision 50);
- **no network** is applied where the host allows it — each body and probe runs
  in a fresh, empty network namespace via `unshare --net`, and the library
  records per run whether it actually applied (`network_isolation_available`,
  `ReplayResult.network_isolated`, revision 54).

The two that remain — a separate **unprivileged user** and a real **disk
quota** — are different in kind. A process cannot drop to another, unprivileged
user without already holding privilege (setuid needs root; a user namespace needs
the capability to create one), and a total disk quota needs a filesystem quota or
a size-capped mount that, again, a process cannot impose on itself without
privilege. Measured in this project's own container: `unshare --net` succeeds
only because the session happens to run as root; a non-root CI runner cannot
create the namespace at all, which is exactly why the library records isolation
rather than asserting it. Implementing user-drop or a quota in library code would
either need a privilege the library cannot assume it has, or would be a no-op that
reads as a guarantee — the "stub that reads like a boundary" this repository
already rejects elsewhere.

## Decision

1. The library enforces only the isolation a process can give itself: the
   process-group kill, the POSIX resource limits, and the network namespace where
   the host grants it, plus the non-privilege defences (the effect guard, the
   argv-template executor, read-only probes, the admission breadth cap). It does
   **not** attempt to switch to an unprivileged user or to impose a disk quota.
2. An **unattended eval against untrusted repositories MUST run inside an
   execution container that the operator configures** to provide: (a) a non-root,
   unprivileged user; (b) a writable area with a total size cap for the sandbox
   root; and (c) either the capability to create a network namespace (which the
   library then uses) or a container-level no-egress guarantee. These are a
   **runner requirement**, recorded in `docs/running-unattended.md`.
3. The library's recorded `network_isolated` is the one isolation fact it can
   verify at run time; the unprivileged user and the quota are **not** verified by
   the library, and `docs/running-unattended.md` says so plainly so no reader
   mistakes a green run for a configured runner.

## Consequences

**Accepted:** the safety of an unattended run now depends on the runner being
configured as documented, and the library cannot confirm the user or the quota
were applied — a misconfigured runner silently loses both guarantees. This is a
real cost: a reader who runs the eval outside the documented container gets the
process-level defences only.

**Gained:** an honest boundary. The library stops at what it can actually
enforce, the two environment-level requirements are explicit and checkable by an
operator rather than implied, and no code pretends to a guarantee it cannot keep
on a non-root host.

**New obligations:** any eval run against repositories not already trusted uses
the documented runner. A later capability probe could record the user and quota
status the way `network_isolated` records the namespace, turning requirement (2)
from documentation into a recorded fact; that is a natural extension of revision
54, not a reversal of this ADR.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Drop to an unprivileged user from library code (setuid / user namespace) | Needs a privilege the library cannot assume (root, or the capability to create a user namespace); on a host without it the call is a no-op that reads as a guarantee. |
| Impose a disk quota from the process (size-capped tmpfs mount) | Needs a mount namespace and privilege; partial and host-dependent, and the per-file `RLIMIT_FSIZE` already caps the one-file case the task family can produce. |
| Refuse to run unless an unprivileged user and a quota are present | Breaks every run on an unconfigured host — local development and this repo's own CI — and there is no portable way to detect a quota, so the check would be unreliable as well as disruptive. |

## What would reverse this decision

- The harness gains a guaranteed-privileged execution layer the library itself
  controls (a rootless-container launcher it owns), making user-drop and a quota
  something the library can apply portably rather than require of the runner.
- A portable, dependency-light mechanism for an unprivileged user and a total
  quota becomes available and the project accepts it as a dependency; then items
  (a) and (b) move from `docs/running-unattended.md` into `runtime` beside the
  network namespace.
