# ADR-0017 — Arm 1b remembers its own trajectories, on its own verdict, in the online mode only

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing (last of issue #7's four baselines; ADR-0014 to ADR-0016 are the others)
- **Deciders:** repository owner

## Context

Claim 1 reads the compiled arms' falling cost against arm 1's flat one. But arm 1
starts every episode from nothing, so its curve is flat **by construction**, and an
engineer would not run an agent that way. Issue #7 asks for arm 1b, "react plus
prior-success memory/reflexion, the standard experience-reuse baseline whose absence
makes the react curve artificially flat". Without it, the amortization the compiled
arms show is measured against a baseline nobody would deploy.

The design had to keep the rule every non-oracle arm lives under: an arm never sees
the fault's checker (issue #9). What 1b stores, and on whose word, were the owner's
choices.

## Decision

1. **Trajectories, not reflections.** An entry (`agents.memory.MemoryEntry`) is the
   request and the git commands that ran without error, in order, capped at
   `MAX_COMMANDS = 12`. Writing an entry costs no extra model call, so 1b's only extra
   cost is the longer prompt, charged through the same accounting as every call.
2. **The model's verdict, never the checker's.** An entry is written when `solve`
   returns `SUCCESS` (the model declared the task done). The write happens inside the
   arm, before `run_episode` runs the fault's checker. A declared-but-wrong episode is
   therefore remembered, as it would be in a real deployment, and a test pins exactly
   that case. A failed episode, or one with no successful command, is not stored.
3. **Recall** returns the `RECALL_K = 3` stored entries whose request is most
   lexically similar to the new one. Ties go to the more recent entry, and an entry
   with zero similarity is never recalled. Lexical similarity is used rather than the
   run's similarity seam so that 1b spends nothing in arm 2's embedding currency.
4. **Placement.** The recalled entries are rendered as a prelude to the **user**
   message, with a warning that they may not apply here
   (`solve(prelude=...)`). The system prompt every arm sends stays byte-identical, so
   the prompt-prefix report stays true. With no prelude, arm 1 is unchanged.
5. **Scope.** One memory per 1b arm per run, grown in occurrence order like an online
   library. No other arm and no replicate starts from it. Rows record
   `memory_recalled`. A **frozen run refuses 1b**, because frozen mode exists so that
   nothing learns mid-run (ADR-0009), and 1b is a baseline for the online cost curve.

## Consequences

**Accepted:** the memory can hold a wrong trajectory and re-teach it. That is the
point of the no-oracle rule: a memory filtered by the checker would hand 1b a
ground-truth signal across episodes that no compiled arm receives. Admission reads a
program's own postconditions, not the fault's checker.

**Accepted:** this task family's requests are deliberately ambiguous. The most similar
past request may have needed a different resolution, so recalled commands can mislead
1b exactly where they mislead arm 2c's lookup. The prelude says so. The interesting
measurement is whether 1b's cost falls anyway.

**Gained:** the cost curve's baseline is no longer flat by construction. If the
compiled arms' amortization survives against 1b, it is not an artefact of a
memoryless baseline.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Written reflections (Reflexion proper: an extra model call per episode writes a lesson, failures included) | Adds an LLM call per episode, and its lessons are model prose that takes up prompt space. The owner chose the cheaper, more literal trajectory store. A reflection variant could be added beside it later without changing this one. |
| Store only checker-graded successes | Gives 1b a cross-episode ground-truth signal, the exception ADR-0014 grants the oracle floor alone. |
| Put the memory in the system prompt | Changes the prefix that every arm is documented to share, and the prompt-prefix report would then be false for one arm. |
| Let 1b learn in frozen runs too | A frozen run withholds learning from every compiled arm. Letting 1b learn there would give it an advantage the run is designed to remove. |

## What would reverse this decision

- An online eval where 1b's recalled trajectories are mostly wrong for the state at
  hand, for instance on the uninformed regime's ambiguous phrasings. That would argue
  for a reflection variant, which can say "that request needed merge, not rebase",
  reported beside this one.
- A run where prompt growth dominates 1b's cost. `RECALL_K` would then need tuning on
  the tune set like any other parameter, with the tuned value recorded.
