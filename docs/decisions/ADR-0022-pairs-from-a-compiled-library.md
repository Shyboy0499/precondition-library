# ADR-0022 — Figure 1's pairs come from the library's own matchers on real sandboxes

- **Status:** accepted (2026-10-02)
- **Date:** 2026-10-02
- **Supersedes:** nothing. It fixes how the outcomes ADR-0008's arithmetic takes are produced from a compiled library, and which pairs they cover.
- **Deciders:** repository owner

## Context

ADR-0008 defined the primary metric over **pair outcomes**, and `bench.primary` (#156)
turns them into Figure 1. But nothing in the repository produced those outcomes from a
compiled library, so the first real Figure 1 (#163) needed a driver outside it (#162).
The existing helpers fit hand-written gold rather than a compiled library:

- `coverage.arm2_outcomes` takes one text per variant. A compiled library holds several
  programs per variant across intents, and it applies its own `admitted` filter and
  tie-break.
- `coverage.arm3_outcomes` takes a caller-supplied decision.
- `pairs.labelled_pairs` crosses *declared* fingerprints, which have no sandbox to run a
  probe in.

The issue also left open which states are negatives: the fault-free sandbox only, or
other faults' states as well.

## Decision

1. `bench.library_pairs.library_pair_outcomes(library, faults, seeds)` builds every
   pair's sandbox and dispatches it through the **library's own matchers**:
   - arm 2: `match_semantic`, unthresholded;
   - arm 3: `match_preconditions`;
   - 2b: `rank_soft`, with its score;
   - 2c: `match_intent_key`.

   The signature is built the way `bench.run` builds it. The library is read, never
   written.
2. **Only the uninformed regime.** The request is `intent.task_text(seed)`, the one the
   episodes send.
3. **The pairs.** Each measured intent's request at each seed is paired with:
   - its own fault's state;
   - the fault-free sandbox, the negative;
   - another fault's state **only when the intent labels it**, which is an overlap state
     as ADR-0019 defines one.

   Another fault's state the intent leaves unlabelled is **not a pair** (`is_pair`).
4. `coverage.arm2_outcomes` and `coverage.arm3_outcomes` are **kept**, for the declared
   grid and the gold probe. Declared fingerprints have no sandbox, and gold has one
   program per variant, which is exactly that form. They are no longer the path for a
   compiled library.

## Consequences

**Gained:**
- The pair-level arms are the arms the episodes run, so a difference between Figure 1
  and the episode tables cannot come from two implementations of one dispatcher.
- Building the pairs found a labelling defect: the submodule intent called a repository
  with no submodule `init`. It is fixed in #158's PR, where ADR-0019 depends on it.

**Accepted:**
- The fault-free sandbox is one environment however many seeds are crossed with it. The
  negatives are therefore one state with many requests: arm 2 and 2c see different text
  each time, while arms 3 and 2b see the same state each time.
- On today's two measured faults, no state of one is labelled by the other's intent, so
  there are no overlap pairs yet.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Pair every intent with every other fault's state, unlabelled ones as negatives | This was tried first. Arm 3 reads only the environment, by design, so it fires the sync program on a diverged state under a *submodule* request. It would be scored wrong for ignoring a request it is built to ignore, in a situation no episode poses. That measures request-blindness, not the dispatch choice Claim 2 compares. |
| Extend `arm2_outcomes` to take a program list | It would still re-implement `match_semantic`'s query, eligibility and tie-break beside the library's own, and the two could drift. The query differs already: `arm2_outcomes` scores the request alone, while `match_semantic` scores the request plus the fingerprint. |
| Both regimes in one call | The metric never pools them (ADR-0004), and the informed channel is not what the episodes send. |

## What would reverse this decision

- An episode design that sends one family's request into another family's state. The
  unlabelled foreign pairs would then be on the episode distribution, and they would
  belong in the metric.
- A measured fault whose states another measured intent labels. Its overlap pairs would
  then appear. If they dominate the positives, the per-intent breakdown would need to be
  reported beside the pooled figure.
