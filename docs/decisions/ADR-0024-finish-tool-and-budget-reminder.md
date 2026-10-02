# ADR-0024 — The agent declares done with a `finish` tool, and is reminded once of its budget

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It adds a second way to declare done; the turn without a tool call still ends the solve.
- **Deciders:** repository owner

## Context

The ReAct agent is every arm's fallback, and #160 made a fallback compilable only when
the agent itself declared the task done. The only declaration the loop recognised was a
turn with **no** tool call.

The second live run (#163) showed the live model never sending one (#171):
- 5 of 8 build episodes ended `FAIL`, and in 3 of them the checker already passed;
- a traced `submodule_moved` solve fixed the repository by turn 8, then re-verified until
  the turn budget ran out;
- every assistant turn had empty text.

The prompt already said "when you are finished, reply with your final answer and no tool
call". No `submodule_moved` program was compiled.

## Decision

1. **A `finish` tool** (`FINISH_TOOL`), with a one-line `summary`, declares the request
   satisfied.
   - The loop returns `SUCCESS` when it is called.
   - Calls batched before it in the same turn run; calls after it do not.
   - It is a declaration, not a command: it does not run, does not appear as a tool
     result, does not count toward `tool_calls`, and is accepted even when the
     tool-call budget is spent.
   - A turn with no tool call still ends the solve, as before.
2. **One budget reminder** (`BUDGET_NUDGE`) is sent as a user message, once, before the
   turn that may be the last. That is the final turn, or the point where at most
   `NUDGE_TOOL_CALL_MARGIN` (4) tool calls remain. It is one fixed sentence about budget
   and says nothing about whether the repository is right.
3. **The system prompt** names both tools and tells the agent to call `finish` as soon as
   the request is satisfied, rather than keep re-checking.

## Consequences

**Gained:**
- The agent can declare done in the form a tool-calling model actually produces.
- An agent that drifts past the fix is told how much budget it has left.
- Both are still the agent's own verdict, so #160's no-oracle rule holds, and arm 1b's
  memory still records only declared successes.

**Accepted:**
- **The prompt every arm sends changes.** The system prefix grows; its length is reported
  by `bench.report.prompt_prefix_lengths`. The tool surface grows by one definition.
  Every arm's fallback is the same agent, so the arms change together.
- **No result is comparable across this change.** Neither live run produced one.
- **The reminder is information a human operator would also have** (the budget). It
  carries no information about correctness. A model could treat it as a cue to stop
  early, which would show up as more `SUCCESS` rows with `ground_truth_ok=False`. The
  ledger already records that quadrant.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Only reword the prompt's stopping rule | The prompt already said to stop without a tool call, and the live model ignored it. A tool is the form the model reliably produces. |
| Stop when the checker passes | Gives arm 1 an oracle the compiled arms never have (issue #9). That is ruled out on `solve` itself. |
| A larger budget | The agent was not short of budget; it never declared done. A larger budget would only spend more before failing the same way. |
| Ask the model to self-assess after the budget runs out | One more model call per failed episode, and a verdict reached after the agent was cut off is not the declaration #160 compiles on. |

## What would reverse this decision

- A live run where `finish` is called on repositories the checker rejects, more often than
  the old path ended correctly. The early declaration would then be costing correctness,
  and the reminder's wording or margin would be the first suspect.
- A model that ends turns without tool calls reliably. The extra tool would then be
  unnecessary surface, though it would do no harm.
