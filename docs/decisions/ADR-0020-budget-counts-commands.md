# ADR-0020 — The agent's budget counts commands, and only a declared success is compiled

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It narrows what `max_steps` alone allowed and what `_run_arm` compiled.
- **Deciders:** repository owner

## Context

Every arm's fallback is the ReAct agent, so its budget and its stopping rule shape the
cost of every arm. In the first live run (#163) two things went wrong.

- **The budget counted turns, not work.** `solve(max_steps=12)` counts model turns, and
  the live model issued 4–5 tool calls per turn. One episode ran about 45 git commands
  under a "12-step" budget while another ran 12, depending only on how the model batched
  its calls. All four `submodule_moved` solves used up the budget exploring, and none
  declared the task done.
- **Failed transcripts were compiled.** `_run_arm` marked every fallback with a transcript
  as compilable, whatever the agent's outcome. So transcripts the agent never declared
  finished were compiled and stored, and two of them were admitted into the frozen library.

## Decision

1. **The budget counts commands as well as turns.** `solve` keeps its 12-turn budget and
   adds `DEFAULT_MAX_TOOL_CALLS = 24`. Once 24 tool calls have run, however they were
   batched, the solve stops with `FAIL` and records "tool-call budget exhausted". The cap
   is twice the turn budget, so an agent issuing one call per turn always hits the turn
   budget first, and the cap binds only on batching.
2. **Rows record `tool_calls`**, the commands the agent executed with refused ones
   included, beside `llm_calls`. A replay records 0.
3. **Only a declared success is compiled.** A fallback is `compilable` only when the agent
   itself returned `SUCCESS`. That is the agent's own verdict, the one the no-oracle rule
   (issue #9) lets an arm act on. The checker's verdict is not consulted, so an agent that
   happened to leave the repository right without declaring it does not get a compile.

## Consequences

**Gained:** the budget means the same thing for every model. A failed solve no longer
pays for a compile, and it can no longer put a program the agent never stood behind into
the library.

**Accepted:** an agent that actually fixes the repository but never says so now produces
no program. The first live run had several such episodes: `fail` outcomes with
`ground_truth_ok=True`. Their cost is now just a failure. Whether the system prompt should
push the model to declare when done is a separate question from what may be compiled.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Ask the API for one tool call per turn | It relies on the provider honouring a flag, and it changes how the agent works rather than what the budget measures. |
| Keep the turn budget and only record tool calls | Makes the variation visible but leaves it uncapped: one model could still spend four times another's commands under the same nominal budget. |
| Keep compiling failed solves, and record their outcome on the provenance | Admission would still have the final say, but compile tokens would still be spent on failures, and the library would hold programs from transcripts the agent itself did not finish. |

## What would reverse this decision

- A model whose good solves routinely need more than 24 commands. The cap would then be
  cutting off success rather than exploration, and its value should be tuned on the tune
  set and recorded.
