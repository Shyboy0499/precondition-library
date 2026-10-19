# ADR-0041 — A sixth family, `config_renamed`, whose state is files rather than git history

- **Status:** accepted
- **Date:** 2026-10-19
- **Supersedes:** nothing. It adds a family and three fingerprint fields, and changes what
  every future measured run includes.
- **Deciders:** repository owner, issue #266 step 1.

## Context

All five registered families are git faults: their situations, discriminators and fixes are
commits, refs and merges. Issue #266 asks whether preconditions stay checkable, and the gap
over text similarity stays wide, when the state is not a git repository's history. Its first
step is one new family with the same contract as the git faults:
- an injector;
- a state grid;
- an intent with paraphrases;
- acceptable resolutions;
- a checker.

Steps 2 and 3 of #266, a replicate build of the new family and one built with a second model,
need a provider key and are not part of this decision.

## Decision

1. **The family is a config migration.** A small synthetic app keeps its settings under
   `config/`, one `key = value` per line:
   - `config/renames.conf` is its table of renamed keys, `old = new` per line; the app warns
     while a config file still sets an old name;
   - `config/settings.conf` holds the project's settings, tracked;
   - `config/local.conf` is an optional per-machine override, git-ignored.

   Like the lock-shaped file of ADR-0029, this is a **synthetic convention, not a real tool's
   format**.
2. **Three live states**, chosen so that different fixed resolutions are right in different
   states:

   | state | the stale key is | resolution | what the obvious wrong fix does |
   | --- | --- | --- | --- |
   | `stale_key` | in `settings.conf`, alone | `rename` it, keeping its value | — |
   | `both_keys` | in `settings.conf`, beside its new name | `drop_old`: delete the dead line | renaming sets the key twice |
   | `local_override` | in the ignored `local.conf` only | `migrate_local`: rename it there, keep the file ignored | editing `settings.conf` fixes nothing; committing `local.conf` publishes a machine's private settings |

   Every state is committed and pushed, so upstream and the clone agree and there is nothing
   to sync. The repository stays a git working tree because the runtime's snapshots, guard and
   bindings assume one, but nothing the request is about is in its history.
3. **The fingerprint gains three fields, read from files, not from git**:
   - `config_stale_keys`;
   - `config_keys_set_twice`;
   - `config_ignored_files`.

   **They are rendered by `as_text` only when set.** Every state before this has none of
   them, so its text is byte for byte what it was. Rescoring a committed run therefore gives
   the committed arm-2 figures, which ADR-0027 to ADR-0029 could not promise when they added
   rendered fields.
4. **Tier 1 axes (ADR-0005):**
   - `key`: which of four renamed pairs is stale;
   - `content`: the values every setting holds.

   Neither moves a state across a rule. Every program can read the table, so a program that
   hard-codes the key it learned on is what the `key` axis exposes.
5. **The checker grades the files, in five clauses:**
   - the rename table and `.gitignore` are untouched;
   - no config file sets an old name;
   - the stale key's file sets the new name exactly once, to the value it must keep;
   - its other settings are unchanged;
   - on `local_override`, `local.conf` is still untracked and `settings.conf` is untouched.
6. **The intent `update_renamed_config_keys` is registered**, with eight phrasings, and gold
   programs that read the rename table rather than a fixed key. Its acceptable sets are
   pinned by replaying every gold body on every state:

   | state | acceptable |
   | --- | --- |
   | `stale_key` | rename |
   | `both_keys` | drop_old |
   | `local_override` | migrate_local |

   Each state accepts exactly its own resolution, unlike the git families, where `merge`
   is accepted widely (ADR-0028).
7. **The admit set gains one episode per resolution** (ADR-0032), at seeds below the tune
   and eval blocks: `rename` at 0 then 7, `drop_old` at 23 then 35, `migrate_local` at 14
   then 18.
8. **The guard recognises a quoted assignment before `read`.** A `key = value` file is
   split with `IFS=' =' read -r key value`. The guard took a `read`'s own assignment only
   when its value had no space, so it read `$key` there as an environment read and refused
   the gold body. A quoted value is now allowed. The names that count as assigned are still
   only those after `read`, and an unassigned name in the same loop is still refused.

## Consequences

**Accepted:**
- **It is synthetic.** It is a config tree, not a real application's config, and its git
  repository is still there, if irrelevant. It answers "does the method work when the
  discriminators are file contents", not "does it work on a real service".
- **The plan grows.** A future `bench.live` run measures six families: 480 labelled pairs
  instead of 400, and admission's unrelated-fault class gains three config states.
  Committed runs are unaffected: rescoring reads the faults from each run's `plan.json`.
- **Easy for text similarity, maybe.** A request about "config keys" names this family more
  plainly than the git requests name theirs. Arm 2 may find the family easily and still have
  to choose among three resolutions it cannot tell apart from the text, which is the
  comparison the family exists for.

**Gained:** the first measured family outside git history, buildable offline, with no change
to any committed figure.

**New obligations:** every other family's rules must refuse a config state, and this
family's must refuse every other state. The intent tests pin both directions.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| A package environment (a virtualenv or `node_modules` out of step with a lock file) | It needs a package manager and a package index in the sandbox, which is network or a vendored index. Neither fits the offline, deterministic sandbox. |
| A service's local state (a stale PID file, a half-applied migration) | Its interesting states need a running process, which the probe snapshot and the process-group confinement treat as something to kill, not to observe. |
| Render the new fields for every state | Every arm-2 text would gain three lines, and every committed arm-2 figure would move on regeneration. |

## What would reverse this decision

A replay showing the checker accepting a resolution the declared set excludes, or the
reverse. A git family's rule labelling a config state, or this family's rule labelling a git
state, would also reverse it.
