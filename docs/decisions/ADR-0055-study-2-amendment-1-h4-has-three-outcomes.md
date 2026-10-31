# ADR-0055 — Amend study 2 before any data: H4 has three outcomes, and only a cost is called one

- **Status:** accepted
- **Date:** 2026-10-31
- **Supersedes:** nothing. It amends `docs/preregistration/refusal-population.md` (ADR-0053) by its
  Amendment 1.
- **Deciders:** the repository owner chose to amend, after the power analysis below was shown to
  them. The wording is the author's.

## Context

A Monte Carlo power analysis of study 2 (`paper/analysis/power.py`) simulated the study under a
generating model calibrated on study 1. It applied the registered statistics and rules through a
vectorised copy of `bench.refusal_population`, checked against it before any power was computed.
It found:

- H1 and H3 have the power §8 states: 0.28 is detected with probability 0.80, and 0.27 with
  0.60–0.70, at study 1's build spread.
- The false-positive rates are 2.8–3.8%, against a nominal 2.5%.
- **H4 cannot show non-inferiority at this size.** With no true cost, it held in 47–53% of
  simulated studies at a calm build spread and in 19–26% at study 1's. The builds' own spread on
  clean cases makes H4's interval about as wide as the 0.10 margin, or twice as wide.

Rule 5 read a failed H4 as a cost: "refusal-tested admission buys declining at the cost of clean
merges". With no cost at all, that sentence would usually be printed.

No case of R or of the evaluation set has been mined, and no build has run, so the registration
may still be amended.

## Decision

1. **Amendment 1** is appended to the registration, and the original text is left in place. Its
   pin in `bench.preregistration` is updated.
2. **H4 has three outcomes.** It *holds* if the interval's lower bound is above −0.10. It finds a
   *cost* if the interval's upper bound is below −0.10. Otherwise non-inferiority is *not shown*.
3. **Rule 5 calls a cost only when H4 finds one.** If H3 is supported and H4 is not shown, the
   finding is that refusal-tested admission lowers the fire rate, and its effect on clean merges
   is not resolved at this size.
4. **Nothing else changes.** The hypotheses, cases, sizes, statistics, margin and rules 1–4 are as
   registered. The false-positive rates are reported, not corrected for.

`bench.refusal_population.h4_outcome` and `decide` implement items 2 and 3, and
`tests/test_refusal_population.py` tests each outcome.

## Consequences

**Accepted:** H4 still cannot confirm non-inferiority at this size in most studies. Under
Amendment 1 such a result is reported as unresolved rather than as a cost. More builds would be
needed to resolve it, and ADR-0053 set the size at 10 per configuration for cost.

**Gained:** rule 5 can no longer report a cost that the data does not show.

**New obligations:** the results report states H4's interval and outcome. It cites this
amendment wherever rule 5's wording differs from the original text.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Leave rule 5 as registered | It would usually report a cost that is not there. |
| Widen the margin until H4 has power | The margin is a judgement about acceptable cost, not a tuning knob, and widening it after seeing its power would change what H4 means. |
| Add builds to give H4 power | ADR-0053 fixed the size for cost. Raising it is a separate decision with a separate price. |
| Drop H4 | Configuration R could then lower the fire rate by firing nothing on clean merges too, and nothing would say so. |

## What would reverse this decision

Nothing about study 2's data can, because the amendment precedes it. A later power analysis that
found H4's width to be much smaller than this one's model implies would make Amendment 1
unnecessary, though not wrong.
