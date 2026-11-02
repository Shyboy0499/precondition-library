# ADR-0057 — Amend study 2 before any data: the first evaluation repository is `opf/openproject`

- **Status:** accepted
- **Date:** 2026-11-02
- **Supersedes:** nothing. It amends `docs/preregistration/refusal-population.md` (ADR-0053) by its
  Amendment 2.
- **Deciders:** the author, on the weekly link check's report (#330). The owner had asked for that
  check's failures to be fixed, never silently.

## Context

The weekly link check found one dead link in the repository's documentation. It was study 2's
first evaluation repository, `openproject/openproject`, which does not exist on GitHub.
OpenProject's repository is `opf/openproject`. The registered name was a slip. Left alone, it
would have stopped study 2's evaluation mining at its first repository, because `pin` cannot
resolve it.

Study 2 has no data: no build has run, and its evaluation set has not been mined.

## Decision

1. **Amendment 2 replaces the name with `opf/openproject`, at the same position.** The original
   line stays as written, as Amendment 1 did. The pin in `bench.preregistration` changes in the
   same commit.
2. **`refusal_study.EVALUATION` follows the amendment.** Its test now checks the registered list,
   the amendment, and the code against each other.
3. **`.lycheeignore` names the original, dead link with its reason.** The link check can then pass
   without the registration's text being rewritten.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Edit the line in §3.1 in place | It would rewrite a registration's text after its commit, which an amendment exists to avoid. |
| Drop the repository from list E | It changes which cases study 2 sees for no reason the registration gives; the intended project exists. |
| Leave it and let mining skip it | `pin` would raise, not skip, and an unplanned skip is a deviation the registration does not describe. |

## What would reverse this decision

Evidence that `openproject/openproject` was meant as a different project. There is none; the list
was written from project names.
