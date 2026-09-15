# ADR-0002 — Run arm 2 as text similarity, lexical now and an embedding behind a seam

- **Status:** accepted
- **Date:** 2026-09-15
- **Supersedes:** nothing (narrows a decision recorded in the design spec and ADR-0001)
- **Deciders:** repository owner

## Context

The design and ADR-0001 describe arm 2 as **embedding dispatch** and state Claim 2
as preconditions-versus-embeddings. That was a plan, not a measurement: no arm had
been implemented and no episode had run.

Implementing arm 2 now forces the choice. An embedding model introduces a
dependency, a network call, and a model-version confound into a dispatch decision
that the rest of the experiment requires to be deterministic and reproducible — the
ledger would have to record the exact model per episode, and a model change would
invalidate affected runs. It also cannot be exercised offline, which the repository's
tests are built around. The owner therefore decided that the arm compares text with a
deterministic lexical function today, behind a seam that a real embedding model can
replace later without touching either arm.

The claim's wording has to change with it. Saying "embedding" while the arm scores
token overlap would be the overclaim CONTRIBUTING rule 1 forbids.

## Decision

1. Arm 2 dispatches by a `Similarity` callable over text, defined in
   `src/precondition_library/similarity.py` as a one-method `Protocol`. The shipped
   implementation is deterministic lexical (Jaccard) token overlap; it is documented
   as a **proxy for** semantic similarity, with surface form as its ceiling.
2. The similarity function is injected at `Library` construction, so replacing the
   lexical function with an embedding model changes neither `match_semantic` nor any
   arm that calls it.
3. Arm 2 receives the full representation: the signature's intent plus the
   `StateFingerprint` rendered as text (`StateFingerprint.as_text()`), per issue #4,
   so the ablation does not confound dispatch with representation. Arm 2 cannot
   *evaluate* that text, which is its actual blindness.
4. The claim, the README, and the design spec describe arm 2 as **text-similarity
   dispatch**. "Embedding" appears only as the intended replacement behind the same
   Protocol, never as a description of what ran.
5. The similarity threshold is a parameter with a documented default, to be tuned on
   the held-out tune seed set and recorded per episode in the ledger's
   `dispatch_score`.

## Consequences

**Accepted:** arm 2's ceiling is surface form. It cannot match a paraphrase that
shares no word with the program text, so a null or negative result may be
attributable to a weak proxy rather than to the mechanism under test. That is a real
threat to Claim 2's fairness and is recorded as a limitation to report, not hidden.
The comparison answers the narrower question "preconditions versus *this* text
similarity" until an embedding is run behind the seam.

**Gained:** dispatch is deterministic, offline, and dependency-free; the dispatch
path stays reproducible and the ledger's model field is not entangled with it. The
seam makes an embedding run a configuration change rather than a rewrite.

**New obligations:** every document that states the claim must keep saying text
similarity; a later embedding run is a new arm configuration whose threshold is
tuned on the disjoint tune set and recorded, and it must be reported as a separate
configuration rather than silently replacing this one.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Embed an embedding model now | Adds a dependency and a model-version confound to a decision that must be reproducible, and cannot run offline. Deferred behind the seam, not dismissed. |
| Drop arm 2 and compare two arms | Claim 2 would have no control arm; review already rejected this because "semantic dispatch was never given a fair shot". |
| Keep saying "embedding dispatch" while scoring lexical overlap | An overclaim (CONTRIBUTING rule 1): the documented mechanism would not be the one that ran. |
| Score text with no state in the query | Reintroduces exactly the representation confound issue #4 exists to remove, and would disadvantage arm 2 by input rather than by mechanism. |

## What would reverse this decision

- The tune set shows the lexical proxy cannot rank the library above chance while an
  embedding can: implement the embedding behind the same seam and report it as the
  configuration actually measured.
- Arm 2 saturates with lexical overlap alone, which would make the proxy's ceiling
  irrelevant to the claim and remove the need for an embedding.
- The claim is restated over a mechanism broader than text similarity, which would
  need a new ADR rather than an edit here.
