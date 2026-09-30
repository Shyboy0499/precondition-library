# ADR-0008 — Sweep arm 2, hold arm 3 as one operating point, and count mismatch per fire

- **Status:** proposed
- **Date:** 2026-09-30
- **Supersedes:** nothing (narrows spec §7 item 1 and Figure 1, which said both dispatchers sweep a threshold; ADR-0001's matched-coverage primary metric stands)
- **Deciders:** repository owner

## Context

ADR-0001 moved the primary metric to the mismatch-versus-coverage curve over labelled
dispatch pairs, compared **at matched coverage**. Spec §7 and Figure 1 then said *both*
dispatchers are swept across acceptance thresholds, and that the directional claim is
stated at a *pre-registered coverage point*. Issue #5 asks for the sweep, the curve with
Wilson intervals, and a power statement. None of it existed, and three things it depends
on were never defined:

1. **Arm 3 has nothing to sweep.** `Library.match_preconditions` returns the admitted
   programs whose preconditions all hold, most specific first. There is no score: a
   program fires or it does not. Arm 2 does have one: `Library.match_semantic` ranks by
   similarity and fires the top program when its score clears an inclusive threshold.
2. **The coverage point had no value.** "A pre-registered coverage point" was written,
   but no number was ever registered.
3. **Mismatch had no stated denominator.** Wrong fires over fires, or over all pairs,
   give different answers, and the second folds coverage back into the rate.

The #5 design comment adds a constraint. Until arm 3's programs are compiled, they are
hand-written and agree with the intents' `decided_by` rules, which are also what label
the pairs. So arm 3 answers every pair correctly by construction, and any curve drawn now
shows one arm that cannot lose. Exercised on the committed gold over the tune seeds, arm
3 played by the labelling rule decides all 96 informed and all 128 uninformed pairs
correctly. Arm 2 traces 7 and 11 operating points respectively.

## Decision

1. **Arm 3 is one operating point.** It is not given an artificial threshold.
2. **The pre-registered coverage point is arm 3's own coverage.** Arm 2's operating point
   nearest it is the matched one. A tie goes to the **lower** coverage, which usually has
   the lower arm-2 mismatch, so the rule cannot be what makes arm 3 look better.
   Distances are compared as exact fractions, and the coverage gap is always reported
   beside the difference.
3. **Arm 2 is swept over every distinct score it produced.** Each distinct score is a
   threshold where the fired set changes, so the curve holds every achievable operating
   point and no interpolated one. The threshold is inclusive, as in
   `Library.match_semantic`.
4. **Coverage is fires over pairs, negatives included. Mismatch is wrong fires over
   fires**, where a fire is wrong when it is not the pair's correct variant, including
   any fire on a negative pair. Each operating point carries a 95% Wilson interval on
   mismatch, and a point that fired nothing has no mismatch rate rather than zero.
5. **Regimes are compared separately and never pooled** (ADR-0004). Every function
   refuses outcomes from both request channels.
6. **The comparison is vacuous while arm 3 decides every pair correctly.**
   `vacuous_reason` says so, and a report prints it instead of the comparison.
7. **The power statement** (§7 item 3) uses a two-proportion normal approximation over
   the two arms' fire counts. α = 0.05 two-sided and power 0.80 are its **defaults**.
   They are not registered as the α for the directional claim; that is left to the
   owner.

`bench.coverage` implements all seven over per-pair `PairOutcome`s, so the arithmetic is
testable before a compiled library exists and cannot depend on either dispatcher's
internals.

## Consequences

**Accepted:** only arm 2 gets a curve. The figure shows one point for arm 3, and "matched
coverage" means "wherever arm 3 happens to land". If arm 3's coverage is very high or
very low, arm 2 is compared at an extreme of its curve. With discrete scores the match is
approximate, and a large gap weakens the comparison; the gap is reported, not hidden.
Per-fire mismatch at low coverage rests on few fires and has wide intervals. The first
real comparison still waits on compiled programs (#4, #7).

**Gained:** the primary metric is now defined precisely enough to compute. The coverage
point is determined rather than chosen, so it cannot be tuned after seeing a curve, and
the definitions are fixed before any data. A comparison against an answer key cannot be
reported as a result.

**New obligations:** the eval report prints `vacuous_reason` before any comparison,
reports the coverage gap, and reports each regime separately. If arm 3 ever gains a
score, for example a learned confidence, this ADR is revisited rather than extended
silently.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Sweep arm 3 over a minimum precondition count | An artificial knob that the mechanism does not have, with only a handful of distinct values. It would give arm 3 a curve by inventing a threshold. |
| Register a numeric coverage point (e.g. 50%) | Arbitrary. It needs arm 3 to be sweepable to reach it, and a number chosen now could still be argued about later; arm 3's own coverage needs no choice. |
| Mismatch per pair (wrong fires / all pairs) | Folds coverage back into the rate, so a dispatcher that rarely fires looks good for that reason alone, which is what matching on coverage exists to prevent. |
| Tie goes to the higher coverage | Usually raises arm 2's mismatch, so the tie-break itself could favour arm 3. |
| Interpolate arm 2's curve to arm 3's exact coverage | Reports a point no threshold achieves. The nearest real point with its gap stated is honest about what was measured. |

## What would reverse this decision

- **Arm 3 gains a real score**, such as a learned confidence over its probes (the soft
  classifier in #7). Then both arms can be swept and matched at a registered point, and
  this ADR is superseded.
- **Arm 3's coverage lands at an extreme** (near 0% or 100%) on the tune set, so that
  matching compares arm 2 only where its curve is degenerate. That would argue for
  registering a numeric coverage point instead, through a new ADR before any eval
  episode.
- After eval data exists the definitions cannot move. That is the point of fixing them
  now.
