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
variant if `FaultSpec.instance_for_seed(seed)` -- the **instance identity** the
injector builds at that seed, the same draw `inject` uses -- has not appeared in
an earlier occurrence of the same fault, and a replay otherwise (ADR-0005
decision 5). It is keyed on the instance and not on the resolution: after the
axis draw a second seed that selects one resolution builds a *different*
environment, so it is a new independent observation, and only a genuine repeat of
one instance is a replay. (Before ADR-0005 the key was the resolution, because
same-resolution seeds built byte-identical environments; that rule counted a new
environment as a repeat.) `FaultSpec.variant_for_seed` returns None for a fault
whose intent is not ambiguous; those faults are refused before any episode runs
(issue #25), and `occurrence_roles` raises for them rather than inventing a role.
A measurable fault whose `instance_for_seed` is None is refused too, rather than
falling back to the resolution.

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
for what a run can pay for, not for what the analysis would like. Since ADR-0005
each measurable fault draws its state shape's content per seed, so the number of
variant occurrences a set holds is the number of distinct **instances** its seeds
build -- not a fixed three. The measured counts, per set and fault, are in each
set's docstring below; a set's length now buys both new instances and replays,
though the instance count is bounded by the draw space and grows sublinearly.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..tasks.faults import FAULTS
from .ledger import OccurrenceRole

__all__ = ["EVAL_SEEDS", "SMOKE_SEEDS", "TUNE_SEEDS", "occurrence_roles"]

SMOKE_SEEDS: tuple[int, ...] = (0, 1, 2, 4)
"""Pipeline shake-out. Until ADR-0032 it was also the build's admit set; the build now
uses `bench.admit_set.ADMIT_SET`, one episode per resolution, and takes these seeds only
when a caller passes them.

Four seeds, so the full repeat structure runs -- four occurrences, with
`occurrence_index` reaching 4 -- through every arm and every measurable fault
family. Its job is to prove the harness runs end to end against a real model
and to produce the first programs that `admit` gates into the library (spec
section 7, "Design": the admit set builds the precondition vocabulary). 4 seeds
x 5 measurable faults x 3 arms is 60 episodes.

The seeds are not `range(4)`: seed 3 injects `repin` for `submodule_moved`, which
seed 2 already injects, so the block 0-3 would never show the `init` state and the
vocabulary admitted from it would have no `init` program. The listed seeds cover
all three injected states of both measurable faults (the injectors' `state_for_seed`
mapping). It is not enough to tune anything or to support any claim, and it is not
meant to be: a smoke run exists to fail loudly on wiring, not to produce a number.

**Roles: 4 variants and 0 replays per family** (measured; ADR-0005). The four
smoke seeds draw four distinct instances for each measurable fault, so the set no
longer revisits an instance and the cost-curve path is not exercised here. That
is the honest cost of keying the role on instance identity: the smoke set still
shakes the pipeline out and admits the vocabulary, and the replay path is covered
by the tune and eval sets. Pinned by `tests/test_seed_splits.py`, which fails if
this silently changes.
"""

TUNE_SEEDS: tuple[int, ...] = tuple(range(1000, 1016))
"""Arm 2's tuning set: 16 seeds, 22 distinct instances across the two families.

Arm 2's similarity threshold is calibrated here and nowhere else, and the value
used is written into every ledger row (spec section 7, item 5). Sixteen seeds
are enough to place one scalar floor on a coarse grid and to check that the
sweep is not flat; they are not enough to fit a *representation* (the lexical
versus embedding choice behind `Library.similarity`) or to compare arms, and no
arm-level claim is read off this set.

The threshold itself is not chosen here. This module fixes which seeds may be
consulted; the tune pass fixes the value.

**Roles (measured; ADR-0005):** `diverged` 15 variants and 1 replay;
`submodule_moved` 7 variants and 9 replays. The threshold is one scalar fitted
over the whole set, so the role counts do not change how it is tuned; they are
recorded because the same labels go onto the rows the tuning is scored from, and
a reader of those rows should not have to infer them.
"""

EVAL_SEEDS: tuple[int, ...] = tuple(range(2000, 2040))
"""The reported numbers: 40 seeds, 80 episodes across the two fault families.

**Roles and instances (measured; ADR-0005).** `diverged` splits 32 variant and 8
replay occurrences; `submodule_moved` splits 15 variant and 25 replay
occurrences. A variant is the first sight of an *instance*, so the number the
mismatch comparison may count is the number of distinct instances the seeds
build, measured on real sandboxes:

| fault | resolution | instances |
| --- | --- | ---: |
| `diverged` | `discard` | 18 |
| `diverged` | `merge` | 8 |
| `diverged` | `rebase` | 6 |
| `submodule_moved` | `init` | 5 |
| `submodule_moved` | `remove` | 5 |
| `submodule_moved` | `repin` | 5 |

That is **47 independent environments**, not 3 and not 40, and not the 24 the
owner set as the target -- the declared draw happens to yield more. The counts are
computed from `FaultSpec.instance_for_seed` before any episode runs and reported
per resolution by `bench.report.achieved_instances`; reproduce the environment
counts with `.venv/bin/python -m precondition_library.bench.instance_diversity`.
A larger set still buys replays; the instance ceiling is the size of the declared
draw space, not the seed count.

The episode-level mismatch comparison can now carry a wider-but-real interval
rather than none at all, but it is still underpowered for the pre-registered
+/-10pp equivalence margin. One arm's 95% Wilson interval near 0.5 is about
+/-18.6pp at N=24 and +/-13.7pp at N=47; the margin, though, is applied by a TOST
to the *difference* of two arms' rates at a 90% interval, whose half-width at 47
per arm and a shared 50% rate is about +/-16.5pp, and +/-10pp first becomes
passable at 133 per arm (`bench.report.tost_equivalence`; ADR-0006, which keeps
the margin). The pre-registered primary comparison is unaffected and lives
elsewhere: it is the pair-level one over labelled (state, program) pairs (spec
section 7, item 1; issue #5), where the state grid is crossed with seeds and no
library accumulates between pairs, and the pair count is chosen for power.

What the forty seeds buy is the cost curve: 8 and 25 replay occurrences per family
are repeat structures long enough to show whether a compiled arm's cost falls and
the baseline's does not, and to survive a few occurrences where no program was
admitted and the arm had to pay. The remaining limitation is that the instances
are draws from hand-written shapes, not a sample of task difficulty, so a variant
rate is a rate over environments the injector can offer and any interval around it
should be read with that in mind. The set is sized this large rather than larger
because each eval seed is a real injected repository and every candidate program
dispatched against it was compiled at LLM cost.
"""


def occurrence_roles(seeds: Sequence[int], fault: str) -> tuple[OccurrenceRole, ...]:
    """The role of each occurrence, in order, for one fault family.

    See the module docstring for the rule and why the roles exist. `fault` must
    have a declared resolution mapping: the benchmark refuses a fault whose
    intent is not ambiguous before any episode runs, so a caller reaching here
    with one has skipped that check, and a role invented for it would be a fact
    about nothing.

    The key is the **instance identity** (`FaultSpec.instance_for_seed`), not the
    resolution (ADR-0005 decision 5): two seeds that select one resolution but
    draw different Tier 1 axis values build two environments, so the second is an
    independent observation rather than a replay of the first. A resolution with
    no instance identity is refused rather than silently keyed on the resolution,
    which is the defect this rule removes.

    This is a pure function of the ordered seeds and the fault's own
    seed-to-instance mapping, so the plan's roles can be computed from the plan
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
        instance = spec.instance_for_seed(seed)
        if instance is None:
            raise ValueError(
                f"fault {fault!r} declares resolution {resolution!r} at seed {seed} but "
                f"no instance identity; independence is keyed on the instance (ADR-0005), "
                f"and falling back to the resolution would count a new environment as a "
                f"replay"
            )
        roles.append(OccurrenceRole.REPLAY if instance in seen else OccurrenceRole.VARIANT)
        seen.add(instance)
    return tuple(roles)
