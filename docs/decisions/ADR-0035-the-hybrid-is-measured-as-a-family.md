# ADR-0035 — Measure the hybrid as a family, and read it at arm 3's coverage

- **Status:** proposed
- **Date:** 2026-10-10
- **Supersedes:** nothing. It adds a third dispatcher beside arms 2 and 3 and the rules it is read by.
- **Deciders:** repository owner, in issue #265. This record states the resolution chosen for that
  issue, so a later reader can tell whether the code complies with it.

## Context

**The question.** Arm 3 fires on about 47% of pairs (187 of 400) and falls back on the rest -- that
is the price of its zero mis-fires. The production gate in the prior work runs the other way round:
semantic recall first, then an executability gate that prunes. A hybrid is what a practitioner would
actually deploy, and whether it keeps arm 3's mis-fire rate at higher coverage is a different and
more useful comparison than either arm alone.

**Nothing new is needed to compute it.** `bench.library_pairs` already builds each pair's environment
and each request's text ranking, and `Library.match_preconditions` already evaluates every admitted
program in that environment. A hybrid decision is a walk down those two lists. What was missing is
that the pass *discarded* both: it kept `accepted[0]`'s variant and the ranking's top-1, and threw
away the accepted set and the rest of the ranking.

**What is new, and why it needs a decision rather than a patch.**

- **Two knobs, and therefore a selection problem.** The hybrid is parameterised by `k` (how far down
  the ranking the gate may look) and by a retrieval floor. A grid of a few hundred points over 400
  pairs means the *best* point is a maximum over many draws: reporting it as the hybrid's number
  would be reporting the luckiest cell, not the mechanism. This is the same family of trap as the
  held-out states of #263 and the sampling variance of #264, in its third form.
- **The hybrid is not arm 3.** It fires by **text rank**, not by arm 3's specificity rank, so it can
  fire a wrong program where arm 3 would have fired the right one -- and it can never fire on a
  negative pair, because the gate is applied per candidate and a fault-free sandbox accepts nothing.
  Both properties are what makes it a third arm rather than a filter on the first two, and both
  belong in the registration rather than in a reader's inference.

## Decision

1. **The hybrid is defined as four steps**, and nothing else is "the hybrid":
   rank the admitted programs by the text scorer, unthresholded; keep those at or above a retrieval
   floor and within the top `k`; fire the **best-ranked one whose preconditions all hold** in the
   environment; if none holds, fire nothing and fall back.
2. **It is derived from the pair pass's record, not rebuilt per point.** `bench.library_pairs`
   records each environment's **accepted program ids** (in arm 3's own order) and each request's
   **complete text ranking** with scores. `score_all` computes every admitted program's score
   whether or not the caller trims the list, so the wider record costs nothing; the grid over it is
   arithmetic. `tests/test_hybrid.py` pins the record against arm 3's own decisions in the same pass.
3. **The grid is registered.** `k` in `(1, 2, 3, 5, 10, None)` (`None` = the whole ranking) crossed
   with every distinct retrieval score plus no floor -- ADR-0008's rule for a sweep: every achievable
   operating point and no interpolated one. Changing either the `k` grid or that rule is a
   pre-registration revision, because it changes which points exist.
4. **The claimable comparison is the point nearest arm 3's coverage**, a tie to the lower coverage
   (ADR-0008), reported with its Wilson interval, the coverage gap, and the smallest detectable
   difference at those fire counts. Every other point is reported as part of the family and not as
   the hybrid's number.
5. **Typing the family's best cell is forbidden; describing it is allowed and bounded.** The widest
   point at which a `k` mis-fired on nothing is reported as a **description of these pairs**, with
   the 95% Wilson upper limit of the mis-fires it did not have. It is never an unbiased estimate of
   the rate at a floor that was chosen because it looked good.
6. **What would falsify the hypothesis**, in the issue's own terms: at arm 3's coverage the hybrid
   mis-fires more than arm 3; or no point above arm 3's coverage is reachable without a rise in
   mis-fires distinguishable at the registered smallest detectable difference.
7. **Arms 3 and 2 are reported beside it.** Arm 3's single pre-registered point and arm 2's own
   curve belong on the same plane, so a reader sees what the gate bought over not gating it. No
   sentence may say the hybrid beats arm 3 beyond what its interval and the detectable difference
   support, and the hybrid's refusal on negative pairs is a property of the gate, not a finding.
8. **A named operating point is tuned on the tune seeds.** A sweep is not tuning and needs none; but
   if `k` and the floor are quoted as *the* hybrid's setting, they are chosen on `TUNE_SEEDS` and the
   record says where they were chosen (the issue's first integrity item). Nothing may be chosen on
   the eval pairs and then quoted as a setting.
9. **It reads the same frozen libraries, read-only.** The stage opens `library-two-sided/` from a
   finished run, compares the digest before and after, and refuses to report if the library moved.
   No model call and no key: the probes are local and the scorer is local.

## Consequences

**Accepted:**

- **The family is not a curve.** A two-knob grid is reported as a family of points on Figure 1's
  plane; the matched point is the one claimable comparison, and a reader who wants "the hybrid's
  number" is given a rule rather than a cell.
- **The descriptive reading carries selection bias it cannot bound.** The widest zero-mismatch point
  per `k` is a maximum; its Wilson limit bounds the rate it did not observe, not the choice that
  found it. Decision 5 says so where the number appears.
- **One scorer, one library per invocation.** The first committed run names its scorer and library;
  the pinned reranker of #256 is a flag and the `embedding` extra away, and the other libraries are
  the same command.
- **The pair pass is the cost.** A few hundred grid points cost nothing once the pass exists, but the
  pass itself is a real sandbox per environment -- about 100 minutes per library on the Windows host
  this was developed on, minutes on Linux.
- **No episode-level claim.** This is a dispatch-level measurement on labelled pairs, like the rest
  of Figure 1.

**Gained:** the deployed shape measured on the same plane, the same pairs and the same frozen
libraries as the arms it is compared with, with the coverage it recovers and the mis-fires it costs
read off one figure; and a record that makes any later re-decision about `k` or the floor free.

**New obligations:** the record must stay the library's own matchers' output (a test pins it against
arm 3's decisions, so a change to either matcher that breaks the derivation fails rather than
silently re-defining the hybrid); the grid and the reading rules may not change without a revision
logged in the spec first; and a committed run must name its scorer and its library digest.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Report the **best** point of the grid as the hybrid's number | It is a maximum over a few hundred cells on 400 pairs. Reporting it would measure the luckiest cell, and the issue's own falsification test is stated at arm 3's coverage for exactly this reason. |
| Report **one tuned operating point** only | It hides the family, and a tuned point has to come from the tune seeds -- which is a legitimate reading, registered as decision 8, but not a substitute for the curve the issue asks for. |
| Treat the hybrid as **arm 3 with a request filter** | That would fire by specificity and only use text to exclude candidates. The deployed cascade fires by text rank and uses the gate to prune; the two differ exactly where the trade-off is (several programs accept the same state). |
| **Rebuild the sandboxes per grid point** | The pass already knows what holds and what ranks where. Re-deciding would multiply a 100-minute pass by the grid size and make the numbers depend on a re-run rather than on one record. |
| Define a **new metric** for the two knobs | The issue asks for Figure 1's plane, and a second metric would make the hybrid incomparable with the arms it exists to be compared against. |
| Count the hybrid's **refusal on negative pairs** as a result | It follows from applying the gate per candidate. It is a property of the construction, and a paper that reported it as a finding would be reporting its own definition. |
| Use the **held-out block** of #263 for the hybrid instead of the eval pairs | The hybrid is a dispatch mechanism, not a state source; the issue registers the same pairs as Figure 1, and mixing an out-of-distribution state set into it would change two things at once. |

## What would reverse this decision

- **The hybrid never reaching arm 3's coverage** on any point of the grid: then the family is
  degenerate at the matched comparison, the matched rule has nothing to match, and the honest result
  is that the gate's pruning costs more coverage than the retrieval recovers.
- **A matched point that mis-fires more than arm 3**, or a coverage gain whose mis-fire rise is
  distinguishable at the registered difference: the hypothesis fails, and the finding is that
  gating text retrieval is not free -- reported as such, with the family shown.
- **A library whose text ranking is not stable between calls**: the derivation assumes the recorded
  ranking is the one the arm would use, and a scorer that answered differently on a re-run would
  break the record's meaning rather than the arithmetic.
- **The reranker landing as the measured scorer**, which changes which ranking the family is built
  from and therefore the numbers, though not the rules.
