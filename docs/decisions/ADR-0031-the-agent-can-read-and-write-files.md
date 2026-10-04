# ADR-0031 — Give the agent a file reader and writer, confined to the working tree

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It changes the agent's tool surface, which every arm solves
  with: arm 1, arm 1b, and every compiled arm's fallback.
- **Deciders:** repository owner (asked for the fix after the fourth live smoke run's
  lockfile results); recorded so the choice can be challenged

## Context

The fourth live smoke run solved no lock-file conflict honestly.

- **The build:** 0 of 4 `lockfile_conflict` solves, so the family had no program to
  admit.
- **The frozen benchmark:** arm 1 and arm 3 solved 0 of 4, and arm 2c 1 of 4.
- **Why:** the resolution is a file rebuilt from both sides, and the agent's only tool
  ran one git command. One solve merged with `git merge-file --union` and spent its
  budget. The one success wrote its blob with `git notes add -m`, staged it with
  `update-index --cacheinfo` and checked it out. Another set a `!sed` alias to edit the
  file through a shell, which #223 now refuses.
- **The baseline was crippled, against its own rule.** `react` says arm 1 must have
  "the same tool surface the compiled programs get", and a compiled body is shell: the
  gold lockfile bodies rebuild the file with `git show`, `sed` and a redirect. The
  dirty-tree collision state, which needs a file moved aside, was out of the agent's
  reach for the same reason.

## Decision

1. **Two tools join `run_git` and `finish`** (`agents.file_tools`).
   - `read_file` reads a working-tree file as it is on disk, conflict markers included.
   - `write_file` replaces a file's whole content, creating directories it needs.
2. **Confined to the working tree.** A path is relative to `env.work`. It is refused
   when it:
   - is absolute, or climbs with `..`;
   - names a `.git` component (config and hooks are how a file becomes a command);
   - passes through or ends at a symbolic link;
   - resolves outside the tree.

   A new file is created without the executable bit. Both directions are capped at
   64 KiB. A refusal is a tool result the agent can read.
3. **The transcript records** `read_file <path>` or `write_file <path>` as the call's
   `command`, so arm 1b's memory keeps the step, and the call's arguments keep the
   content. Both tools count toward `max_tool_calls`.
4. **The compile prompt says how to translate them.** A body has no such tools: it reads
   with `cat` or `git show`, and makes a write's change with shell. It computes the
   content from the repository rather than pasting the agent's text, which belongs to
   one repository.

## Consequences

**Accepted:**
- **Arm-1 and fallback numbers are not comparable across this change.** Every solve
  sees two more tools and a longer system prompt, in every family.
- **Every call's prefix grows** by the two schemas and four prompt lines. It is the
  same prefix on every call, so it caches.
- **A compiled lockfile program still has to rebuild the file in shell.** The compile
  step now sees an honest solution to generalise. The guard limits #214 lists (a
  `while read` variable, a `/`-addressed `sed -i`) may still refuse a body that
  does it, and are an owner decision there.

**Gained:**
- **The baseline has the surface its rule promises**, so a family whose resolution is a
  file is measured on the agent's judgement, not on how well it knows git plumbing.
- **No reason left to escape.** The two escapes the live agent found (a notes blob and a
  `!` alias) were what an agent does without a writer.

**New obligations:**
- The next live run's report should give the lockfile family's solve rate, so the
  change is measured and not assumed.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| A shell tool | The tool runs git without a shell so that `rm -rf ...` is a refusal. A file writer gives the one capability a chore needs and nothing else. |
| `git apply` from a patch the agent supplies | Still needs the patch written somewhere, and a whole-file write is what a person resolving a conflict does. |
| A conflict-resolution tool that takes "ours" or "theirs" | It names the resolutions, so it would hand the agent the answer the benchmark measures. |
| Leave the agent git-only | The family would measure plumbing tricks, and an agent without a writer reaches for escapes. |

## What would reverse this decision

- A solve that uses the writer to leave the repository in a state the checkers pass but
  a person would not accept, more often than solves without it did.
- A way out of the working tree through these tools. That would be a confinement bug,
  fixed in `file_tools`, not a reason to keep the agent git-only.
