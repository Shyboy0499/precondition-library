# ADR-0001 — Re-center the project on the open measurement

- **Status:** accepted
- **Date:** 2026-09-13
- **Supersedes:** the claims as originally stated in the design of record
  (`docs/superpowers/specs/2026-09-13-precondition-library-design.md`)
- **Deciders:** project owner

## Context

The design of record originally claimed two things: that compiling a task into a
persistent program and replaying it without an LLM amortizes cost (Claim 1), and
that choosing which program to replay by testing executable preconditions
mis-fires less often than choosing by embedding similarity (Claim 2). Claim 2 was
declared primary.

Two reviews were run before any implementation.

**A prior-art sweep** found that Claim 1 is not merely anticipated but
well-established, and that Claim 2's *mechanism* is decades old:

| Finding | Work |
| --- | --- |
| Compiles a task trace into a persistent program and replays it, faster, with no per-step LLM calls | PreAct (arXiv:2606.17929) |
| Compiles GUI trajectories into parameterized templates, replays with zero LLM calls | SkillDroid (arXiv:2604.14872) |
| Compiles witnessed-deterministic agent spans into signed artifacts gated on differential replay, deopting to the paid agent on guard trip | Auto: The AGI Compiler (arXiv:2607.04542) |
| Builds a reusable parameterized tool from demonstrations; a cheaper model then invokes it | LATM (arXiv:2305.17126, ICLR 2024) |
| Dispatches a cached generalized plan by testing **executable precondition kernels** against live state, with an explicit replan fallback | MACROPS (Fikes, Hart & Nilsson, 1972) |
| An option's initiation set plays the role a precondition plays for a policy | Options (Sutton, Precup & Singh, 1999) |
| The most similar case is not necessarily the most appropriate for reuse | Smyth & Keane (1998) |

**A hostile method review** then found that the experiment as designed could not
have supported Claim 2 even if the mechanism had been novel. The fatal finding:
each fault returned a fixed diagnostic sentence, so the task text *was* the
ground-truth label and semantic dispatch could not mis-fire by construction. Four
further defects were found — pseudo-replication across occurrences, an admission
gate that differed between the arms being compared, a tautological "equal success
rate" (both compiled arms fall back to the ReAct baseline), and the absence of
the baselines that would make the control arm credible. These are tracked in
issues #3–#10.

**A verification pass** checked every citation found by the sweep. All of them
are real — none was fabricated — but five attributions were wrong and are
corrected in the design of record: LATM was cited for "zero LLM calls" when its
replay phase still calls an LLM; the `SameCapRisk-Bench` figures were attributed
to that paper's earlier title; a Smyth & Keane line was quoted as verbatim when
it is a paraphrase; an option's initiation set was described as *identical* to a
precondition rather than analogous to one; and MACROPS was dated 1971 rather than
1972.

One verification failure was ours, not the sweep's: the sweep claimed the
`alcheme-labs/dsh-experience-map` repository publishes "no control arm, no
matched-library comparison, and no mismatch metric". That is false — the
repository contains `docs/decisions/m7-three-arm-evaluation.md` and
`docs/release/BENEFIT_EVIDENCE.md`. The claim was repeated internally before it
was checked. **The lesson is now the rule: no citation, positive or negative,
enters the README or the spec until the verification pass has confirmed it.**

## Decision

**1. Claim 1 is dropped as a contribution.** Compile-once replay is established
prior art. It remains useful as an engineering assumption and as a cost model,
and is reported as such — never as a finding.

**2. Claim 2 is narrowed to its empirical form, and that becomes the project.**
The mechanism is classical. What no confirmed work does is *measure the
comparison*: at matched dispatch coverage, does executable-precondition dispatch
mis-fire less often than embedding dispatch, where "mis-fire" is scored as an
outcome orthogonal to success or failure? The closest works bracket this question
without answering it:

- A deployed deterministic executability gate (arXiv:2608.01050) prunes 59.4% of
  matched skill–message pairs and, in a gate-removed counterfactual, the model
  selected a non-executable skill in 7.8% of conversations — but the gate is a
  *cascade after* semantic recall, so it can only prune, never rescue a recall
  miss, and no head-to-head comparison is reported.
- A retrieval risk benchmark (arXiv:2606.10388v2) measures top-K exposure of
  harmful sibling skills at HSR@3 0.346–0.372 for public retrievers versus 0.007
  for a controlled resolver — but that is retrieval exposure, not wrong-program
  execution at matched coverage.

**3. The measurement becomes the spine of the repository; the agent becomes its
harness.** The primary metric moves from an episode-level paired mismatch
difference to a dispatch-level benchmark over labelled (repo-state,
candidate-program) pairs, swept across acceptance thresholds and reported as a
mismatch-versus-coverage curve with Wilson intervals and an explicit power
statement. The end-to-end episode loop
survives as a small demonstration, clearly labelled underpowered.

**4. The pre-registered analysis is revised before any data exists.** No episode
has been run. The original pre-registration is superseded rather than
reinterpreted, and this revision is recorded here precisely so that the change is
visible and cannot be mistaken for an analysis chosen after seeing results.

## Consequences

**Accepted:** the project no longer claims a novel architecture. The framing that
motivated it — "build a different kind of agent" — is demoted: what ships is a
benchmark, with the agent as its instrument. A reviewer can now say "this is
MACROPS for git chores, measured" and be *correct about the mechanism* while the
measurement remains genuinely open.

**Gained:** a hypothesis that prior art does not already answer, so it can be
tested rather than merely restated; a control arm that can actually lose; a
pre-registration that is honest about revision; and a decision record that
explains why the repository looks the way it does.

**New obligations:**

- Every citation is checked against the source by the author before publication
  (see the correction above). This is a hygiene pass, not independent review.
- The negative-sandbox admission criterion — admit a program only if it passes
  postconditions on a faulted instance *and* fails preconditions on generated
  negative states — becomes the most likely artifact-level contribution, since
  prior art publishes postcondition-gated admission only. It is reported as a 2×2
  factor against an otherwise identical positive-only gate.
- Issue #3 (intent-underdetermined instances) is a prerequisite for the primary
  metric to be measurable at all.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Keep the agent central, add an honest prior-art section, restate the claims | Preserves the original vision, but the headline becomes "a modern instance of a classical mechanism". Honest and modest — and it invites "MACROPS for git chores" as the summary. The measurement is the only thing here that is actually open. |
| Abandon the project | The narrow gap is real and unmeasured, the engineering is already scaffolded, and the remaining work is days rather than weeks. Abandonment would be a reaction to losing a claim, not to losing the question. |
| Publish as-is and cite prior art only superficially | Not considered seriously: a public novelty claim contradicted by 1972 is a reputational cost with no upside. |
| Keep the original pre-registration and analyse the pilot anyway | The fatal flaw makes the primary metric degenerate. Analysing it would produce a number that looks like a result while measuring nothing. |

## What would reverse this decision

- **The dispatch-level benchmark shows no difference between mechanisms at any
  coverage.** Then the honest finding is "executable preconditions buy no
  dispatch accuracy over embeddings in this domain", which is a legitimate
  negative result — but the repository becomes a negative-result report, and the
  negative-sandbox admission factor becomes the whole contribution.
- **Executable probes require domain knowledge that embeddings do not.** If
  writing the precondition vocabulary turns out to encode the answer, the
  comparison is confounded by author effort rather than measured, and the design
  must change again.
- **The fault domain proves too easy.** If injected faults leak detectable
  markers, semantic dispatch wins for the wrong reason. Issue #3's text-only
  classifier AUC is the control that detects this.
