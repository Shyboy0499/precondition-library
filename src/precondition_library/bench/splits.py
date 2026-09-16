"""The seed plan: which fault seeds may influence which stage of the experiment.

The pre-registration splits fault seeds into disjoint sets -- one to admit the
programs and shake the pipeline out, one to tune arm 2's similarity threshold,
and one on which the reported numbers are computed (spec section 7, "Design",
and items 2 and 5 of "Pre-registered analysis"). Until this module existed that
requirement was prose only: no concrete seeds were defined anywhere, so the
first run against a real model could not have honoured it.

**Why this is fixed in code rather than chosen at run time.** A split decided
after seeing scores is not a split. The ledger records `seed` on every episode
(spec section 7, "Ledger"), so a reader can map each row back to the set it came
from -- but only if the sets were knowable in advance. A split chosen per run
would make that mapping unverifiable and would let the evaluation set be picked
to flatter a result. Because these values are frozen before any data exists,
changing one is a pre-registration revision, logged in the spec's revision
history and not applied silently (CONTRIBUTING rule 8).

**Why tuples and not sets.** `run_benchmark` consumes seeds positionally
(`seeds[occurrence - 1]`) and every arm is routed through the same (fault, seed)
pairs, so the pairing across arms has to be reproducible. A `set` declares no
order, which would make that pairing a property of the interpreter rather than
of the plan. Each set below is therefore a tuple in ascending order -- the order
`sorted()` would give -- so an accidental reorder is visible in review and is
pinned by `tests/test_seed_splits.py`. The gaps between the blocks are
deliberate: a later edit that adds a seed to one set cannot silently land inside
another's range.

These split the fault *injection* seeds. They are unrelated to the train/eval
seeds in `tests/test_task_text_is_not_a_label.py`, which split the request-text
control, not the injected environments.

**Sizing, honestly.** A real episode is an LLM loop, so these counts are chosen
for what a run can pay for, not for what the analysis would like. Only the two
fault families in `registry.ambiguous_intents()` are measurable, and each seed
injects one state per family, so a set of N seeds is N independent instances per
family. Each set is described below with what it is and is not enough for.
"""

from __future__ import annotations

SMOKE_SEEDS: tuple[int, ...] = (0, 1, 2, 4)
"""Pipeline shake-out, and the admit set for the precondition vocabulary.

Four seeds, so the full repeat structure runs -- four occurrences, with
`occurrence_index` reaching 4 -- through every arm and both measurable fault
families. Its job is to prove the harness runs end to end against a real model
and to produce the first programs that `admit` gates into the library (spec
section 7, "Design": the admit set builds the precondition vocabulary). 4 seeds
x 2 measurable faults x 3 arms is 24 episodes.

The seeds are not `range(4)`: seed 3 injects `repin` for `submodule_moved`, which
seed 2 already injects, so the block 0-3 would never show the `init` state and the
vocabulary admitted from it would have no `init` program. The listed seeds cover
all three injected states of both measurable faults (the injectors' `state_for_seed`
mapping). It is not enough to tune anything or to support any claim, and it is not
meant to be: a smoke run exists to fail loudly on wiring, not to produce a number.
"""

TUNE_SEEDS: tuple[int, ...] = tuple(range(1000, 1016))
"""Arm 2's tuning set: 16 seeds, 32 instances across the two fault families.

Arm 2's similarity threshold is calibrated here and nowhere else, and the value
used is written into every ledger row (spec section 7, item 5). Sixteen seeds
are enough to place one scalar floor on a coarse grid and to check that the
sweep is not flat; they are not enough to fit a *representation* (the lexical
versus embedding choice behind `Library.similarity`) or to compare arms, and no
arm-level claim is read off this set.

The threshold itself is not chosen here. This module fixes which seeds may be
consulted; the tune pass fixes the value.
"""

EVAL_SEEDS: tuple[int, ...] = tuple(range(2000, 2040))
"""The reported numbers: 40 seeds, 80 instances across the two fault families.

This is the set the primary comparison would be computed from, and it is
**too small to support it as pre-registered.** The primary metric is the
mismatch-versus-coverage difference between dispatchers at matched coverage,
reported with Wilson intervals and a required power statement (spec section 7,
items 1 and 3). Eighty decisions cannot put a usable interval around a
difference at any but a very large effect size, so an interval from this set
would span zero and settle nothing. The honest reading is that 40 seeds buy a
first estimate and a check that the curve behaves as expected -- not the
primary claim. Stating the claim requires extending the pair count under the
extension rule (item 6) and, if it still spans zero, reporting "no difference
detected at this N" with the interval shown.

The set is sized this large rather than larger because each eval seed is a real
injected repository and every candidate program dispatched against it was
compiled at LLM cost; a several-hundred-seed eval set is what the analysis
wants and is not what a run has so far been able to pay for.
"""

__all__ = ["EVAL_SEEDS", "SMOKE_SEEDS", "TUNE_SEEDS"]
