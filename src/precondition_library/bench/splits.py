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

**Two kinds of occurrence, and why the plan has to name which is which.** A set
of seeds is a sequence of *occurrences*, and they are not all the same kind of
thing. The first time a run sees a resolution of a fault, no program admitted
from that state can be in the arm's library yet, so the episode is an independent
observation. Every later occurrence of the same resolution meets a state the run
has already seen, so a program admitted for it earlier can answer the episode for
nothing -- which is the amortization the cost curve exists to show, and which
also makes that observation *dependent* on the episode that admitted the program.
The first kind is a **variant**, the second a **replay**. Conflating them is how
a cost curve gets computed over the occurrences where it cannot bend, or an
interval gets computed over one observation counted many times.

Both requirements are real, and they pull apart: amortization needs a state to
recur, independence needs an occurrence that is not a rerun of the one that paid
for the program. Naming the roles is what lets each analysis take the occurrences
it is entitled to -- the cost curve the replays, the mismatch comparison the
variants (spec section 7, "Ledger" and "Figures"). `occurrence_roles` below
applies the rule to an ordered seed sequence; `tests/test_seed_splits.py` pins
the role counts of each set, and the runner writes the role onto every ledger row
rather than leaving a reader to re-derive it.

**The rule.** Scanning a set's seeds in declared order, an occurrence is a
variant if `FaultSpec.variant_for_seed(seed)` -- the resolution the injector makes
correct at that seed, the same mapping `inject` uses -- has not appeared in an
earlier occurrence of the same fault, and a replay otherwise. It is keyed on the
resolution and not on the seed, because the resolution is what a program matches
on: two different seeds that select the same state are answered by the same
program, so an occurrence is not independent merely because its seed is new.
`FaultSpec.variant_for_seed` returns None for a fault whose intent is not
ambiguous; those faults are refused before any episode runs (issue #25), and
`occurrence_roles` raises for them rather than inventing a role.

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
for what a run can pay for, not for what the analysis would like. Every
measurable fault's injector declares exactly three states, so a set of N seeds
holds **at most three variant occurrences per family** however large N is; the
rest are replays. A set's length buys replay occurrences -- repeat structures for
the cost curve -- and does not buy independent observations. Each set below is
described with what it is and is not enough for.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..tasks.faults import FAULTS
from .ledger import OccurrenceRole

__all__ = ["EVAL_SEEDS", "SMOKE_SEEDS", "TUNE_SEEDS", "occurrence_roles"]

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

**Roles: 3 variants and 1 replay per family.** The replay is occurrence 4 for
`diverged` (seed 4 selects the `overlapping_files` state seed 0 also selects) and
occurrence 3 for `submodule_moved` (seed 2 selects `repin`, which seed 1 already
selected). One replay per family is enough to exercise the replay path and not
enough to read a cost curve off: the demo's curve is a wiring check, which is why
the pass it was first run in reported its zero-call replays as a mechanism rather
than as a number (README, "First demonstration").
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

**Roles: 3 variants and 13 replays per family.** The threshold is one scalar
fitted over the whole set, so the role counts do not change how it is tuned;
they are recorded because the same labels go onto the rows the tuning is scored
from, and a reader of those rows should not have to infer them.
"""

EVAL_SEEDS: tuple[int, ...] = tuple(range(2000, 2040))
"""The reported numbers: 40 seeds, 80 episodes across the two fault families.

**Roles: 3 variant and 37 replay occurrences per family.** Each measurable
fault's injector declares exactly three states (`diverged.INJECTED_STATES`,
`submodule_moved.INJECTED_STATES`), so a set of any length yields at most three
variants per family; every occurrence after the first sight of a state is a
replay.

That is the arithmetic the mismatch comparison depends on, and it is not forty:
**three independent observations per family**, six across the two families,
because the wrong fire a later occurrence makes is the same program the variant
that admitted it has already counted. A larger set does not change this -- the
ceiling is the number of states the injectors declare, not the number of seeds --
so the honest reading is that the episode loop cannot support the episode-level
mismatch comparison at any seed count. The pre-registered comparison is
unaffected and lives elsewhere: it is the pair-level one over labelled
(state, program) pairs (spec section 7, item 1; issue #5), where the state grid
is crossed with seeds and no library accumulates between pairs.

What the forty seeds do buy is the cost curve: 37 replay occurrences per family
is a repeat structure long enough to show whether a compiled arm's cost falls and
the baseline's does not, and to survive a few occurrences where no program was
admitted and the arm had to pay. The remaining limitation is that the three
states are not a sample of task difficulty -- they are the whole population the
injector offers -- so a variant rate is a rate over three states that were
written by hand (issue #6's held-out variants are what would widen it), and any
interval around it should be read with that in mind. The set is sized this large
rather than larger because each eval seed is a real injected repository and every
candidate program dispatched against it was compiled at LLM cost.
"""


def occurrence_roles(seeds: Sequence[int], fault: str) -> tuple[OccurrenceRole, ...]:
    """The role of each occurrence, in order, for one fault family.

    See the module docstring for the rule and why the roles exist. `fault` must
    have a declared resolution mapping: the benchmark refuses a fault whose
    intent is not ambiguous before any episode runs, so a caller reaching here
    with one has skipped that check, and a role invented for it would be a fact
    about nothing.

    This is a pure function of the ordered seeds and the fault's own
    seed-to-resolution mapping, so the plan's roles can be computed from the plan
    alone -- before a sandbox exists, and identically in the runner, in
    `tests/test_seed_splits.py`, and by anyone reading a ledger.
    """
    spec = FAULTS[fault]
    seen: set[str] = set()
    roles: list[OccurrenceRole] = []
    for seed in seeds:
        resolution = spec.variant_for_seed(seed)
        if resolution is None:
            raise ValueError(
                f"fault {fault!r} declares no seed-to-resolution mapping, so an "
                f"occurrence of it cannot be labelled variant or replay; the "
                f"benchmark refuses such a fault before any episode runs"
            )
        roles.append(OccurrenceRole.REPLAY if resolution in seen else OccurrenceRole.VARIANT)
        seen.add(resolution)
    return tuple(roles)
