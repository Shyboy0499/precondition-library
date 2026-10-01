# Running an unattended eval safely

Replay runs model-authored shell and git with no model and no human in the loop,
against repository content an attacker may control. The library enforces every
isolation a process can give itself; two isolations need privilege a process
cannot grant itself, so the **execution container** must provide them. This page
is the operator's half of that contract. The rationale is ADR-0013; §9 of the
design spec is the threat model.

This matters only for an eval against repositories you do not already trust.
The test suite and local development build throwaway sandboxes from the project's
own fixtures and need none of this.

## What the library already enforces

You do not configure these — they are in `runtime/`:

- **Process-group kill on timeout.** A body or probe that backgrounds work cannot
  outlive the timeout (`runtime.confine`).
- **Per-file size limit and no core dumps** on POSIX (`RLIMIT_FSIZE` = 256 MiB,
  `RLIMIT_CORE` = 0). This caps one runaway file; it is **not** a total quota.
- **No network, where the host allows it.** Each body and probe runs in a fresh,
  empty network namespace (`unshare --net`) when the host can create one. Whether
  it actually applied is recorded per run (`ReplayResult.network_isolated`); a
  host that withholds the privilege falls back to the guard's textual screen.
- **The effect guard, the argv-template executor, read-only probes, and the
  admission breadth cap** (design spec §9).

## What the runner must provide

| Requirement | Why the library cannot do it | How to provide it |
| --- | --- | --- |
| **Unprivileged user** | Switching users needs root or a user namespace the process may not hold. | Run the container as a non-root UID. |
| **Total disk quota** | A filesystem quota or size-capped mount needs privilege the process lacks; the per-file `RLIMIT_FSIZE` is not a total cap. | Mount the sandbox root as a size-capped volume or tmpfs. |
| **No network** (belt) | `unshare --net` needs the capability to create a namespace, which a non-root host may deny. | Remove networking at the container level, so egress is impossible regardless of in-container privilege. |

The library **does not verify** the user or the quota; only `network_isolated`
is recorded. A green run is not evidence the runner was configured — this page is.

## A worked example (Docker)

```bash
docker run --rm \
  --user 1000:1000 \
  --network none \
  --read-only \
  --tmpfs /work:rw,size=512m,mode=1777 \
  --workdir /work \
  <image> \
  <command that builds the library / runs the eval under /work>
```

- `--user 1000:1000` — the unprivileged user. Nothing in the eval needs root.
- `--network none` — no egress at all, independent of in-container privilege.
  This is the belt; the library's `unshare --net` is the suspenders, and with
  `--network none` there is no interface for it to isolate in the first place.
- `--tmpfs /work:…,size=512m` — a size-capped writable area for the sandboxes
  (`.sandboxes/` and the ledger). The cap is the total quota the library cannot
  impose; 512 MiB is far above what a run writes and far below a host disk. Point
  the ledger and the sandbox root inside `/work`.
- `--read-only` — the rest of the filesystem is read-only, so a body can write
  only under the capped `/work`.

A rootless container runtime (Podman, or Docker in rootless mode) gives the same
guarantees without the daemon running as root, and is the better default where
available.

## If you cannot provide these

Then do not run unattended against untrusted repositories. The process-level
defences still hold, but the unprivileged user and the total quota do not, and a
body that exhausts the disk or runs as a privileged user is then only as
contained as the host it runs on. Running compiled programs against real
repositories already requires human review of each program (design spec §9); this
page is the environment that review assumes.
