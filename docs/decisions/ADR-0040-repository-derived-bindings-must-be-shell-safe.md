# ADR-0040 — A repository-derived binding must be shell-safe, or it is not bound

- **Status:** accepted
- **Date:** 2026-10-18
- **Supersedes:** nothing. It narrows what `runtime.probes.bindings` and
  `repository_bindings` (#181) may return.
- **Deciders:** repository owner.

## Context

A probe or body names its inputs as `{placeholders}`. `substitute` pastes each bound value into
the text as written, and the text runs under `bash -c`. The harness binds fixed values. A
checkout (#181) derives three from the repository:
- `upstream_remote`, from its remotes;
- `upstream_branch`, the remote's recorded default branch, which the trusted pre-fetch refreshes
  with `git remote set-head --auto`;
- `submodule_path`, the first path in `.gitmodules`.

Someone other than the user writes two of them. The remote's owner names its default branch, and
git allows `;`, `$`, `(`, `)`, `|`, `&`, `>` and quotes in a branch name. Anyone who can commit
writes `.gitmodules`.

**Measured before this change.** A remote whose default branch was named `x;>PWNED` made the
probe `git rev-parse --verify {upstream_remote}/{upstream_branch}` create `PWNED` in the
checkout. The guard screened the substituted text and let it through, because writing inside the
tree is something bodies need. The snapshot refused the probe as one that changed the sandbox,
but only after the command had run. A body is substituted from the same mapping.

The argv templates (`runtime.templates`) already validate their bound values, but probes and
shell bodies did not.

**A second, smaller defect.** Both readers of `.gitmodules` split git's plain output on
whitespace and kept the last word, so a submodule at `my lib` was bound as `lib`. That is a
valid-looking path that is not the submodule.

## Decision

1. **A repository-derived value is bound only if it is `shell_safe`:**
   - letters, digits and `._/+-` only;
   - no leading `/` (an absolute path) and no leading `-` (an option);
   - no `..` component.

   Anything else stays **unbound**. A program that needs it is then *not applicable*, the
   ordinary non-match. On a checkout, `upstream_ref` raises `NoUpstreamError`, as it does for any
   checkout whose upstream cannot be derived.

   The rule applies to `upstream_remote`, `upstream_branch` and `submodule_path`, in both
   `bindings` and `repository_bindings`, so the harness and a checkout still agree.
2. **`work_dir` is not screened.** It is the sandbox's directory, or the one the user ran the tool
   in. It is chosen by whoever runs the tool, not by the repository.
3. **One reader of `.gitmodules`, with `-z`**: `sandbox.gitmodules_path`, used by both the
   harness and the checkout path, returns a path whole.

## Consequences

**Accepted:** a repository with a legitimate but unusual name is refused, not served. That
covers a submodule directory with a space or a non-ASCII character, and a branch with `@` or `,`
in it. The refusal is in the safe direction: the program does not run, and on a checkout the CLI
says it found no usable upstream. Widening the charset means arguing, character by character,
that the shell cannot read it.

**Gained:** nothing the repository supplies reaches a shell as anything but a plain word.
`tests/test_shell_safe_bindings.py` pins the measured case: no `PWNED`, and the probe reported
not applicable. With the screening removed, it and the two `.gitmodules` cases fail.

**Unchanged:** every value the harness binds is `upstream`, one of the five branch names its
faults use, or `vendor/libcore`. All are shell-safe, so no harness binding and no committed
figure moves. The harness-agreement tests in `tests/test_repository_bindings.py` pass for
every measured state.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Shell-quote every substituted value | It changes what existing programs mean: many already write `"{submodule_path}"`, which would become a literal-quoted string. It also gives no help where a value is spliced into a larger word. |
| Rely on the guard | The guard screens commands, not where a value came from, and it allows writes in the tree because bodies need them. The measured case passed it. |
| Validate only `submodule_path`, as the templates do | The measured injection came through `upstream_branch`. |
| Refuse the whole checkout on one unsafe value | An unrelated program that needs only `work_dir` would be refused too; leaving the one name unbound refuses exactly the programs that need it. |

## What would reverse this decision

A program executor that never builds shell text from bound values: the compile step emitting
argv-template `steps` only (#4's territory). Then values travel as argv elements, and the charset
could widen to what git itself allows.
