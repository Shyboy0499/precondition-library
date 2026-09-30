# ADR-0010 — Run the admission factor as one compile gated twice, with "ungated" meaning positive-only

- **Status:** proposed
- **Date:** 2026-09-30
- **Supersedes:** nothing (implements issue #4's 2×2 and arm 3-prime on ADR-0009's frozen library)
- **Deciders:** repository owner

## Context

Issue #4 asks for "the 2×2 factorial {dispatch: semantic|precondition} × {admission:
gated|ungated}" and for "arm 3-prime (precondition dispatch, positive-only admission)".
The spec's Figure 3 describes that 2×2 as separating the negative-sandbox criterion
(Claim 3) from predicate dispatch (Claim 2). Claim 3 itself is to be "reported as a 2×2
factor against an otherwise identical positive-only gate". Arm 3-prime is therefore not
a separate arm: it is the {precondition, positive-only} cell of the 2×2.

Three things had to be settled:

1. **What "ungated" means.** Admission has four parts: pre-sandbox contract checks (a
   declared variant; every body parameter named by a precondition), the positive side
   (postconditions hold on a faulted sandbox), and three negative-sandbox classes (clean,
   unrelated faults, same-intent siblings). Claim 3 is about the negative sandboxes only.
2. **How the two libraries are made.** Compiling separately for each gate would let a
   model's run-to-run variation into the admission factor. The two cells would differ in
   their programs as well as in their gate.
3. **How a row says which cell it is in.** The dispatch arm is on every row. The
   admission condition was not recorded anywhere.

## Decision

1. **"Ungated" is `AdmissionGate.POSITIVE_ONLY`.** It runs every check before the
   positive side, and the positive side, identically, and skips exactly the three
   negative-sandbox classes. The factor therefore isolates the negative-sandbox
   criterion, and nothing else about admission varies.
2. **One compile, gated twice.** `build_library(positive_only_root=...)` stores each
   compiled program in the two-sided root (as ADR-0009 describes) and gates the same
   program again, positive-only, into the second root. The two libraries hold the same
   programs and differ only in which ones each gate admitted.
3. **Each root records its gate.** A `build.json` manifest names the gate, faults and
   seeds. It is not a program, so neither `load_all` nor `library_hash` sees it.
4. **Rows carry the gate.** `EpisodeRecord.admission_gate` is `two_sided` or
   `positive_only`: from the manifest in the frozen mode, `two_sided` in the online mode,
   and `None` for arm 1. A frozen library with no manifest records `None`, which is an
   unknown gate, not a guess.
5. **`report.admission_factorial` builds the table.** It has one cell per (arm, gate),
   over graded variant episodes, with coverage (fires over episodes) and per-fire
   mismatch as in ADR-0008. It refuses rows with an unknown gate, and a gate whose rows
   span more than one `library_hash`, because a cell must be one library that both
   dispatch arms faced.

## Consequences

**Accepted:**
- The pre-sandbox contract checks stay in the ungated arm, so "ungated" is not "no
  gate". A reader expecting an entirely unfiltered library should know this.
- The positive-only library can only be larger than or equal to the two-sided one:
  every two-sided admission also passes positive-only. So the cells differ in coverage
  as well as in mismatch, and the table reports both.
- The episode-level cells are small (the admit set is four seeds per fault), and the
  table inherits the episode loop's underpowered label. The pair-level version is
  `bench.coverage` run over each library.

**Gained:** Claim 3 can be measured as its own factor, with the admission condition
recorded on every row. Arm 3-prime exists as one cell, without a new arm type.

**New obligations:** a factorial run uses both roots from one build, with each root's
manifest intact. The report cites both hashes.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| "Ungated" = no admission at all | Also drops the pre-sandbox contract checks, so the factor would measure more than the negative-sandbox criterion Claim 3 is about. |
| Compile separately per gate | Lets the model's run-to-run variation into the admission factor. |
| Arm 3-prime as a fourth `Arm` value | It is a cell of the 2×2, not a different dispatcher. A new arm would duplicate dispatch logic that §4 keeps to one function. |
| Infer the gate from `library_hash` | A hash does not say which gate produced it. The manifest does, and the row records it. |

## What would reverse this decision

- The owner reading Claim 3 as "any admission versus none". Then the ungated arm drops
  the contract checks too, through a new ADR before any eval pass.
- Evidence that the pre-sandbox checks reject most compiled programs on their own. The
  positive-only library would then barely differ from the two-sided one, and the factor
  would be measuring the contract checks' absence of effect. That would be worth
  knowing, and would argue for reporting the checks as a third level.
