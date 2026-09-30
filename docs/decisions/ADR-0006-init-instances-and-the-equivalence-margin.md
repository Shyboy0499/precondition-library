# ADR-0006 — Count `init`'s instances by the content their gitlink names, and keep the ±10pp margin with its power stated as a TOST

- **Status:** proposed
- **Date:** 2026-09-30
- **Supersedes:** nothing (settles the two questions issue #86 left to the owner after ADR-0005 landed; ADR-0005 stands)
- **Deciders:** repository owner

## Context

ADR-0005's Tier 1 draw landed and #86 stayed open on two questions, both recorded
in the issue as the owner's call rather than something a measurement could settle.

**1. Is `submodule_moved/init` five environments or one?** Measured over the 60
plan seeds with real sandboxes (`bench.instance_diversity`), `init`'s 22 seeds draw
five instances. Before resolution the five clones are byte-identical: `.gitmodules`,
`app.py` and `docs/readme.md` match and `vendor/libcore` is empty. The only
difference is the upstream gitlink, a 40-hex **commit** id in the nested
repository. That id is not cosmetic, though. Each of the five resolves to a
distinct nested commit, tree and `lib.py` blob, and running the correct resolution
(`git submodule update --init`) materialises different bytes: seed 2003 yields
`VERSION = 100 ... RELEASED = False`, seed 2005 yields `VERSION = 7 ... NAME = "libcore"`
(#86, 2026-09-29 audit). So "different SHAs, same content" (#86's excluded case)
does not describe it. What does describe it is "same pre-resolution surface,
different content behind a pointer". Whether that counts as a new environment is
a reading, not a measurement.

The audit also found a weakness in the measurement itself: `instance_signature`
compared the upstream tree by `git ls-tree -r`, which prints a gitlink's commit id.
For `init` that id was the *only* thing distinguishing the instances. So the
signature inferred content diversity by following a pointer; it did not witness it.

**2. What does the ±10pp equivalence margin need?** Spec §7 item 10 pre-registers a
**TOST on the difference between arm 2's and arm 3's success rates**, at ±10pp and
α = 0.05 (a 90% interval), with Agresti–Coull-adjusted variance
(`bench.report.tost_equivalence`). Revision 38's underpower note, and the #86 comment
that proposed restating the margin, measured this with a **single rate's 95% Wilson
interval**: ±18.6pp at N=24, ±13.7pp at N=47 (revision 39), ~94 for ±10pp. That is
a different quantity. A difference of two rates has roughly √2 times the variance of
one, and the TOST uses a 90% interval rather than a 95% one. Measured with the
repository's own function, both arms at the same observed rate (the most favourable
case for passing):

| per-arm N | half-width at 50% | at 70% | at 80% | at 90% |
| ---: | ---: | ---: | ---: | ---: |
| 24 | 22.5pp | 20.9pp | 19.2pp | 14.9pp |
| **47** (achieved) | **16.5pp** | 15.2pp | 13.4pp | 11.0pp |
| 94 | 11.8pp | 10.9pp | 9.6pp | 7.3pp |

±10pp first becomes passable at **133 per arm** at a 50% rate (132 fails, 133
passes), 87 at 80% and 53 at 90%, and only if the arms' observed rates are
identical; any observed difference needs more. The owner's first answer, restating
the margin to ~±14pp, was given against the single-rate figure. Against the TOST,
±14pp cannot pass at 47 per arm unless both arms succeed at about 80% or more.

Strength of the evidence: the instance counts and the nested content are measured
on real sandboxes. The TOST table is exact arithmetic from `tost_equivalence`, with
"per-arm N" read as independent environments (revision 38's unit). The success
rates the run will see are unknown, which is why the table has columns.

## Decision

1. **`submodule_moved/init` counts as five environments.** The content a correct
   resolution materialises is part of the environment, including when it sits behind
   an uninitialised gitlink. The counts stand at **61 plan / 47 eval**, all six
   resolutions stay in the comparison, and ADR-0005 decision 7's exclusion is not
   applied to `submodule_moved`.
2. **The signature witnesses that content rather than inferring it.**
   `bench.instance_diversity` expands every gitlink in the upstream tree into the
   nested commit's blob lines (`_gitlink_content`). No commit id enters
   `instance_signature`, and a gitlink that resolves nowhere is kept as a visible
   `unresolved` line rather than dropped.
   `tests/test_instance_diversity.py::test_gitlinks_are_compared_by_the_content_they_name`
   pins this. The measured counts are unchanged by it.
3. **The equivalence margin stays at ±10pp, α = 0.05.** §7 item 10 is not revised.
4. **The power statement is made in the TOST's own terms.** Live text states the
   difference's 90% half-width from `tost_equivalence` (±16.5pp at 47 per arm at a
   50% rate) and the ~133 per arm ±10pp needs. It keeps the single-rate Wilson
   figures only as what they are: the interval around one arm's rate. Tests pin the
   TOST figures to the function, as revision 39 did for the Wilson ones.
5. **Nothing in the report changes.** `success_rate_wording` already says
   "comparable" whenever the interval is wider than the margin, which is the
   expected verdict at the achieved N.

## Consequences

**Accepted:** the episode loop will very probably not be able to print "equal
success rate". At 47 per arm that needs both arms at ~80%+ and nearly identical.
Otherwise the report says "comparable" and labels the run underpowered, as §7 item
10 intends. Keeping `init` at five also accepts that its instances are
indistinguishable before resolution, and that one command, `git submodule update
--init`, is correct for all of them. A program admitted on one `init` instance will
likely replay identically on the others. The five are therefore independent as
environments but may be less independent as dispatch observations than the count
suggests.

**Gained:** the pre-registration is unchanged, so no margin was moved after
reasoning about what the data could reach. The power statement now measures the test
the margin is applied to. And the `init` count is backed by a comparison that
contains no commit id.

**New obligations:** every live statement of the episode loop's power cites
`tost_equivalence`, not a single-rate interval. If Tier 2 axes (#6) raise the
instance count, the power statement is restated from the same function. Claim 2's
support stays with the pair-level mismatch analysis (§7 item 1), not with this test.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Collapse `init` to one instance | The owner's reading is that content behind the gitlink is part of the environment. Collapsing would remove `submodule_moved` under ADR-0005 decision 7, leaving 56 plan / 42 eval environments and 5 resolutions. |
| Keep `init` at five on the old signature | It would rest the count on a commit id, the identity #86 refuses. The same count with a content-level comparison costs one function. |
| Restate the margin to ~±14pp | This was the first answer, based on the single-rate figure. Against the TOST it cannot pass at 47 per arm at a 50% rate, so it would widen the claim without making the test decidable. |
| Widen the margin to ~±17pp | This is the narrowest margin that can pass at 47 per arm at any rate. But "equal within 17 points" is a weak claim, and a margin chosen to fit the achievable N is what §7 item 10 registers against. |
| Drop the equivalence test | That would remove the one mechanism that stops "no detected difference" being written as "no difference". Keeping it costs nothing: it says "comparable" when underpowered. |
| Raise the target to ~133 per arm | This keeps ±10pp decidable, but it needs more drawable axes than Tier 1 has (the parameter binding in #6), so it is out of scope here. It is not ruled out as later work. |

## What would reverse this decision

- **`init`:** evidence that no arm can observe the nested content before acting. That
  would mean a probe, a program and the agent all see identical inputs on every
  `init` instance, and the instances then add no dispatch information. It would argue
  for collapsing `init` to one, through a new ADR, before any eval pass.
- **The margin:** a judgement, before any eval data exists, that "comparable" is not
  an acceptable reported outcome for Claim 2's success-rate comparison. That would
  argue for a widened margin or for raising N. After eval data exists the margin
  cannot move; that is the point of registering it.
- **The power statement:** a change to how `tost_equivalence` computes its interval,
  such as pairing the arms by environment. Paired variance could be much smaller, so
  the table would be re-derived from the new function.
