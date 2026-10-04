# ADR-0030 — Give a refused compile one revision, told why it was refused

- **Status:** accepted (2026-10-04)
- **Date:** 2026-10-04
- **Supersedes:** nothing. It changes how a solution becomes a program (spec §6): one
  compile, then at most one revision. It narrows ADR-0010's "compiled once, gated
  twice": the two libraries share each episode's first compile, and only the
  two-sided one can hold a revision.
- **Deciders:** repository owner (agreed after the fourth live smoke run's build);
  recorded so the choice can be challenged

## Context

The fourth live smoke run's build admitted 4 programs out of 20 builds.

- **Every `diverged` program was refused.** Each fired on the renamed-branch
  `local_work` state, which looks like ordinary diverged work except that the branch
  follows a name upstream dropped. ADR-0028 added that state to the negatives. The
  refusals are correct, because a diverged resolution leaves the wiring stale there.
- **The model was never told why.** `_learn_from_solution` compiled once, and
  admission's reason went to the ledger and nowhere else. So no compile could learn
  that a precondition was missing.
- **Most other refusals were of the same kind:** a sibling state the preconditions
  also accepted, or a postcondition that failed on the positive side. In each, the
  reason names exactly what to change.

The gate itself is not the problem: it refused programs that would have misfired. The
build's problem is that a refusal is a dead end.

## Decision

1. **`COMPILE_ATTEMPTS = 2`** in `bench/run.py`. When admission refuses a compiled
   program, `_learn_from_solution` compiles once more and judges the revision by the
   same `admit`, unchanged. There is no third attempt.
2. **The revision sees the refused program and the reason.** `compile_program`'s
   `revision=(program, reason)` puts both into the payload as `previous_program` and
   `admission_refusal`, inside the same untrusted block as the transcript, because the
   reason quotes the model's own program. The system prompt gains a note saying what
   the two keys are.
3. **What is stored:** the last program that parsed, with its verdict.
   - If the revision is admitted, it is the stored, admitted program.
   - If it is refused too, it is stored as a candidate, and the row keeps its reason.
   - If the revision does not parse, or raises, the first program and its reason stand.
4. **Every attempt's tokens are the episode's.** The ledger records `compile_attempts`
   (`None` when nothing was compiled, including on older rows).
5. **It applies wherever a solution is compiled:** the build, and the online arms that
   grow their own library.
6. **The refused first program is kept.** When a revision is stored, the stored
   program's `history.jsonl` gains a `revised` event carrying the refused program and
   its reason (`Library.record_revision`). A rejected program is data
   (`library/README.md` rule 1), and nothing else would hold it.
7. **The build's positive-only library is gated on the first compile**
   (`Library.first_compile`). The revision is the two-sided gate's feedback: the
   positive-only gate has no negative side, so it never produced the refusal the
   revision answers. Gating the revision positive-only would give the ungated library
   programs shaped by the gate it is the control for.

## Consequences

**Accepted:**
- **A build costs up to one more compile per refused program.** On the fourth smoke
  run that would have been 11 extra compile calls on 20 builds: every refusal of a
  program that parsed.
- **Admission numbers are not comparable with runs before this.** A build's admission
  rate now measures "admitted within one revision". The ledger's `compile_attempts`
  lets a report separate first-attempt admissions from revised ones.
- **The online arms' cost curve moves.** A fallback that compiles twice spends more on
  the occurrence that pays. The cost is in the row, so the curve reports it rather
  than hiding it.

- **The admission factor now measures the gate together with its feedback.** Where a
  program was revised, the 2x2's two libraries hold different programs for that
  episode, so a two-sided cell's difference includes what the revision changed. A
  revision can also answer a positive-side refusal, which the positive-only gate
  would have refused too and does not revise. The build's ledger rows give
  `compile_attempts`, so a report can restrict the factor to first-attempt programs,
  where the two libraries still hold the same program.

**Gained:**
- A refusal becomes information the compiler can act on. This is the mechanism the
  gate was always meant to feed: a program that names the state it must refuse.
- The gate is unchanged, so nothing it admits is weaker. A revised program passes
  exactly the checks a first-attempt one does.

**New obligations:**
- The next live run's report should give first-attempt and revised admissions
  separately, so the revision's effect is measured and not assumed.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Tell the compiler every negative state up front | It would put the whole negative class into every prompt, cost-heavy, and it turns admission's test set into training data. A refusal names only the state the program actually fired on. |
| Compile the positive-only library separately | Two compiles per episode would put the model's run-to-run variation into the admission factor, which is what ADR-0010's single compile prevents. |
| Gate the revision in both libraries | The positive-only library would hold programs shaped by the two-sided gate's refusals, so the control would carry part of the treatment. |
| Revise only in the online arms | The build's 4-of-20 admission was the failure that prompted this; leaving the build without a revision leaves the frozen comparison with nearly empty libraries. |
| Retry until admitted | Unbounded spend, and a gate passed by search rather than by understanding. One revision answers "can it act on the reason?"; more answers "can it guess?". |
| Relax the gate for states another family owns | The refusals were correct: a diverged program that fires on a renamed-branch state does the wrong thing there. |

## What would reverse this decision

- Revised programs admitted by the gate but misfiring in the frozen benchmark at a
  higher rate than first-attempt ones. That would mean the revision teaches the
  model to evade the gate's sample rather than to target the state.
- A revision that rarely turns a refusal into an admission, so the extra spend buys
  nothing.
