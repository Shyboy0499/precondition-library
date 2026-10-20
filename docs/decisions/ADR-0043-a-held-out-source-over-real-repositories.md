# ADR-0043 — A held-out source over real repositories' histories

- **Status:** accepted
- **Date:** 2026-10-20
- **Supersedes:** nothing. It adds a sixth held-out source beside the five ADR-0033, ADR-0037,
  ADR-0039 and ADR-0042 registered.
- **Deciders:** repository owner, issue #263.

## Context

Every state the held-out stage builds still starts from the generator's two-file base:
`app.py`, `docs/readme.md` and one commit. The five held-out sources change a name, a path or
a shape inside that base. None changes the base itself. So nothing measured whether a compiled
program depends on the base being tiny: a tree with two files, a history of one commit, no
`.gitignore`, no other project's conventions. The README said "real repositories are not
measured".

## Decision

1. **A sandbox's history can start from a pinned public repository** (`sandbox.RealHost`).
   - Upstream's bare repository holds the pinned commit and the 50 commits before it.
   - The generator's base is committed on top, and the fault is injected exactly as before.
   - A shallow history cannot be pushed into an empty repository, so the fetched cache is
     copied in as upstream and `main` is pointed at the pinned commit.
2. **The host is chosen by a scoped resolver** (`sandbox.real_host_bases`). Inside the block,
   `create(seed, …)` starts from the seed's host; outside it, or for a seed it maps to None,
   nothing moves. Every caller, the injectors and the held-out stage run unchanged.
3. **Four hosts, pinned by commit** (`bench.realhost.REAL_HOSTS`):

   | host | language | commit | note |
   | --- | --- | --- | --- |
   | `psf/requests` | Python | `611c616` | |
   | `pallets/click` | Python | `2247b35` | merges, so the depth-50 fetch holds 341 commits |
   | `junegunn/fzf` | Go | `55c122f` | its `.gitignore` ignores `vendor` |
   | `expressjs/express` | JavaScript | `0dee2c5` | |

   Each commit is its default branch's tip on 2026-10-20. Only the URL and the commit are
   recorded here; the content is fetched by commit into a cache under `.sandboxes/`, never
   committed. A fetch by commit gives the same objects anywhere, so a rerun builds the same
   states.
4. **The seeds are the eval block** (2000–2039), ten per host in turn. Each state is one
   Figure 1 measured on the synthetic base, so the comparison is paired and a difference is
   the base's. The seeds are below `HELD_OUT_SEED_BASE`, so no held-out name or path is
   mixed in.
5. **The fetch is the harness's own step**, the only one that reaches the network. It runs
   under the operator's environment, never the scrubbed one model-authored code gets. Probes
   and bodies still run only in the disposable sandbox. Nothing here points a program at a
   real repository: the sandbox holds a copy of a real history.
6. **`submodule_moved` adds its submodule with `--force`.** fzf ignores `vendor`, and git
   refuses to add an ignored path without it. A repository can hold a submodule there. The
   synthetic base has no `.gitignore`, so its states are byte-identical, checked at 16 seeds
   including held-out ones.
7. **The measurement is `bench.heldout.run_held_out`, unchanged**, one block per host and
   fault (`bench.realhost`), so each block reads and is recounted like a held-out block.

## What it found

On all three committed libraries every state built, and every label held (the label check runs
inside `build_sandbox`). Each block is 10 positives and 10 fault-free negatives.

| | run-11 | run-12 | run-13 |
| --- | --- | --- | --- |
| arm 3 fires on the 200 positives | 187 | 187 | 189 |
| of them wrong | 0 | 0 | 0 |
| fires on the 200 fault-free negatives | 0 | 0 | 0 |
| Figure 1, synthetic base, same seeds | 187 | 187 | 189 |

Every positive arm 3 sat out is a `lockfile_conflict` state, and on exactly the seeds it sits out
on the synthetic base (`results/abstentions-2026-10-12/`): 13, 13 and 11, with none missed on one
base and fired on the other. The other four faults fired on all 40 of their positives in each
library. A second path rebuilt every state and evaluated every admitted program directly, and it
agrees on all 60 blocks. It counted a fire as wrong if any program that held belonged to another
fault or named a resolution the state does not accept, and found none.

## Consequences

**Accepted:**
- **Four repositories are not a sample of repositories.** They are small, well-kept projects,
  chosen for their languages and for one `.gitignore` interaction.
- **The fault is still the generator's.** The base is real; the dirty files, the divergence,
  the lock file and the submodule are still injected. A state no injector builds is not
  measured.
- **Measuring needs network**, once per host.

**Gained:** the README's "real repositories are not measured" is narrowed to "real faults are
not measured". Whether the programs depend on a tiny base is now measured, on four hosts.

**New obligations:** a host is pinned by commit, never by branch. Appending a host moves the
seed-to-host mapping, so it is added deliberately, as `REAL_HOSTS` says.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| A new seed block (4000–4039) | Seeds above `HELD_OUT_SEED_BASE` draw held-out names and paths, so the base would be confounded with them. |
| The real tree flattened into one commit | It misses a program that misreads a long history; the owner chose the real history. |
| Committing the hosts' content | It would vendor four other projects into this repository. The commit pin gives the same states without it. |
| Skipping fzf for `submodule_moved` | It would hide the one real interaction the hosts produced. |

## What would reverse this decision

A pinned commit that can no longer be fetched. The stage would then need a mirror, or a new
pin and a new measurement.
