# ADR-0052 — Real merges falsify "arm 3 rarely mis-fires"; H2's margin is the control's scope, not execution

- **Status:** accepted
- **Date:** 2026-10-27
- **Supersedes:** nothing. It records the outcome of the registered study (ADR-0048, ADR-0049), and
  it narrows what the project may claim from Figure 1.
- **Deciders:** the registration's §9 rules, applied as written; the reading of H2 is the
  author's, stated here so it can be challenged.

## Context

Stage B of the real-merge study is measured (`results/real-merges-2026-10-26/stage-B/`). It has
274 cases from 11 repositories and is not underpowered. Its figures were recomputed independently
from its outputs. Its labels were re-derived from git for 55 of the cases (20%), and all 55 agree.

## Decision

1. **The claim that arm 3 rarely mis-fires is falsified on real lock-file merges** (§9 rule 2). Arm
   3's Wilson lower bound of mismatch is 0.338 and 0.478 in two of the three libraries, against
   the rule's 0.10. The near-zero mismatch of Figure 1 holds on the project's synthetic states,
   and is not to be stated as holding beyond them.
2. **H1, H2 and H3 are supported as registered**, in every replicate, and are reported as such.
3. **H2's support is not to be read as evidence that executing preconditions beats reading the
   state.** The registered control decides with the lock-file intent's own tree, whose classes are
   that intent's resolutions and "none". It cannot fire `merge`. Arm 3 searches the whole library,
   and Amendment 1 (A2) counts any intent's `merge` as right on a clean case. Arm 3's right fires
   are its `merge` fires on clean cases: all 113 clean cases are labelled `merge`, and the control
   fires on none of them. On conflicted cases, where both can fire, arm 3 is right on 1 of 177
   fires and the control on 1 of 160. The paired check found no discordant pair in any replicate.
   So the margin is the difference in what each may fire. ADR-0047's wording stands.
4. **No library resolves a real lock-file conflict.** One of 161 conflicts is expressible by the
   intent's resolutions. This repeats stage A's finding, at five times the size.
5. **The design flaw in 3 is recorded, not repaired.** A control scoped to the whole library, or an
   arm 3 scoped to the requested intent, would compare like with like. That is a new study, to be
   registered before its data (ADR-0048), not a re-analysis of this one.

## Consequences

- The README's headline (#300) must say that Figure 1's near-zero mismatch is measured on
  synthetic states, and that on real merges arm 3 mis-fires on 8–54% of its fires, depending on the
  library.
- The registered H2 sentence ("executing preconditions, rather than reading the state, is what
  wins") is not used, for the reason in decision 3.
- What stage B supports is narrower: arm 3 fires `merge` on clean merges where lexical similarity
  does not, and two of three libraries mostly decline to fire on conflicts nothing can resolve.

## Alternatives considered

- **Report H2 as a win for executability**, because §2 licenses it. Rejected: the registered
  comparison cannot distinguish executing preconditions from being allowed to fire another
  intent's program. Using the sentence would claim more than the measurement shows.
- **Re-analyse H2 on conflicted cases only, and report that as the result.** Rejected as the
  result, since it would be a post-hoc test. The breakdown is reported descriptively instead.
