# ADR-0051 — A sandbox can provide cargo, through homes inside its own root

- **Status:** accepted
- **Date:** 2026-10-27
- **Supersedes:** nothing. It extends what `run_env` hands a body, for sandboxes that ask.
- **Deciders:** repository owner (the full rebuild, ADR-0050); the boundary is the one argued
  below.

## Context

Real lock-file conflicts are resolved with the ecosystem's tool (#306). The rebuilt
`cargo_lock_conflict` fault has states where the right action *is* a cargo command: reconcile a
side's `Cargo.lock`, or move one crate on. For a learned program to do that, the body it runs
must be able to call cargo.

The scrubbed environment (spec §9) passes a body only `PATH`, the locale, the temporary
directory and a `HOME` inside the sandbox. rustup's shim, found on `PATH`, needs `RUSTUP_HOME`
to find a toolchain, and by default reads it from the operator's home. Passing the operator's
`RUSTUP_HOME` or `HOME` through would hand model-authored code a path into their dotfiles, which
is exactly what the allowlist exists to prevent.

## Decision

1. **`sandbox.provide_rust_toolchain(sandbox)`** creates a `RUSTUP_HOME` and a `CARGO_HOME`
   *inside the sandbox root*. It links the operator's toolchain directory (from
   `rustc --print sysroot`) into the first; the second starts empty.
2. **`run_env` adds `RUSTUP_HOME`, `CARGO_HOME`, `RUSTUP_TOOLCHAIN` and `CARGO_NET_OFFLINE`
   only for a sandbox that has them.** Every other sandbox's environment is unchanged.
3. **`cargo_lock_conflict` provides the toolchain at injection**, and refuses to inject without
   one, because its injector needs cargo too.

## What a body can now see, and why that is acceptable

- **Paths inside the sandbox root**, which it could already see.
- **The link's target: the compiler toolchain's directory.** It holds binaries and the standard
  library, not credentials. `PATH` already names the toolchain's `bin` directory (`~/.cargo/bin`)
  for every body today.
- **No registry.** `CARGO_NET_OFFLINE` and the empty network namespace (`runtime.confine`) mean
  cargo resolves only from what the repository vendors.

A body that runs `cargo build` can execute a build script. That is no capability a shell body
lacked: it already runs arbitrary commands, inside the same confinement.

## Consequences

**Accepted:**
- On a platform that refuses to create the link (Windows without the privilege), the sandbox
  has no cargo, and `cargo_lock_conflict` does not inject there. The fault's tests are not in
  the Windows job.
- The fault's tests require cargo and fail without it rather than skip.

**Gained:** a lock-file fault whose right actions are the ones maintainers take.

**New obligations:** any further tool a fault provides gets the same treatment: homes inside the
sandbox, added to `run_env` only when provided, and an ADR.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Allowlist `RUSTUP_HOME`/`CARGO_HOME` from the operator | Model code would read paths into the operator's home and could write the operator's cargo cache. |
| Copy the toolchain into each sandbox | Over a gigabyte per sandbox. |
| Grade package sets only, with no cargo for programs | The right actions would be unperformable, so admission could only ever admit programs that hand-edit lock files. |
