# ADR-0025 — When a budget runs out, the agent gets one last word with only `finish` on offer

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It amends ADR-0024: the reminder stays, and a final turn is added after it.
- **Deciders:** repository owner

## Context

ADR-0024 gave the agent a `finish` tool and one budget reminder. In the third live run
(#163) that worked for 6 of 8 build episodes. The other 2 failed the same way (#179):
- the reminder arrived when this model, which batches 4–5 commands per turn, had about one
  batch left (after 20 and 22 of 24 calls);
- the agent used that batch to make the fix, then sent a verification batch that overran
  the cap before it could call `finish`.

Both repositories were fixed, and neither produced a program.

## Decision

1. **Calls past the tool-call cap are answered, not run.** Each gets a refusal result
   marked `not_run`, so the conversation stays valid for the provider. They are not
   counted in `tool_calls`, since nothing ran.
2. **When either budget is spent** (the tool-call cap, or the 12-turn budget), the agent
   gets **one last turn** (`LAST_WORD`). It is told no command will run, and **`finish`
   is the only tool offered**.
3. **Only `finish` counts as done on that turn.** A plain reply, a call to anything else,
   or a provider error is `FAIL`, recorded with which budget ran out. On every other turn,
   a reply with no tool call still ends the solve as before.

## Consequences

**Gained:** a repository the agent fixed with its last batch is no longer lost to its own
verification. The verdict is still the agent's: nothing here consults the checker.

**Accepted:** an exhausted episode costs one more model call. The `LAST_WORD` prompt could
draw a premature `finish`, which would show as `SUCCESS` with `ground_truth_ok=False`;
the ledger already records that quadrant, and the transcript sidecar shows the turn.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Send the reminder earlier (≤ 8 calls left) | Still a guess at the model's batch size. This model fixed the repository *in* its reminder turn, so an earlier reminder only moves the same overrun earlier. |
| Keep the turn going past the cap so a later `finish` in the batch counts | Only helps when `finish` is in that batch. In both live failures it wasn't. |
| Grade the repository when the budget runs out | That's an oracle in the stopping rule (issue #9), ruled out on `solve` itself. |

## What would reverse this decision

- A live run where the last word produces `finish` on repositories the checker rejects
  more often than it rescues fixed ones.
