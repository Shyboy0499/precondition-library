"""The seed plan's properties, which are the whole reason it is a module.

The split is the experiment's integrity property: tuning on a seed that later
appears in the evaluation set contaminates the result, and a split chosen after
seeing scores is not a split. These tests exist so the plan cannot regress into
something that merely looks like one -- overlap, a non-integer seed, an empty
set, or a `set` whose iteration order is not declared.

The second half of the file pins the **roles**. Which occurrences are independent
observations is the arithmetic the whole report rests on, so it is asserted here
rather than described in a docstring: the counts below are the plan's claims
about itself, and a seed list edited without re-deriving them fails.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from precondition_library.bench.ledger import OccurrenceRole
from precondition_library.bench.splits import (
    EVAL_SEEDS,
    SMOKE_SEEDS,
    TUNE_SEEDS,
    occurrence_roles,
)
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.registry import ambiguous_intents

SETS = {
    "smoke": SMOKE_SEEDS,
    "tune": TUNE_SEEDS,
    "eval": EVAL_SEEDS,
}

MEASURABLE_FAULTS = sorted(intent.fault for intent in ambiguous_intents())

#: (variant occurrences, replay occurrences) per family, as each set's docstring
#: claims. Three variants is not a choice: it is the number of states the
#: injectors declare, and it is the same for every set however long the set is.
DECLARED_ROLE_COUNTS = {
    "smoke": (3, 1),
    "tune": (3, 13),
    "eval": (3, 37),
}


def test_the_three_sets_are_pairwise_disjoint() -> None:
    """The point of the file. Overlap between tune and eval is contamination."""
    names = sorted(SETS)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            overlap = set(SETS[first]) & set(SETS[second])
            assert not overlap, (
                f"{first} and {second} seeds overlap: {sorted(overlap)}; the split "
                f"exists so tune is disjoint from eval (spec section 7, item 5)"
            )


@pytest.mark.parametrize("name", sorted(SETS))
def test_each_set_is_non_empty(name: str) -> None:
    assert SETS[name], f"the {name} seed set is empty; a set with no seeds runs nothing"


@pytest.mark.parametrize("name", sorted(SETS))
def test_every_seed_is_a_non_negative_integer(name: str) -> None:
    for seed in SETS[name]:
        assert type(seed) is int, f"{name} contains {seed!r} of type {type(seed).__name__}"
        assert seed >= 0, f"{name} contains a negative seed: {seed}"


@pytest.mark.parametrize("name", sorted(SETS))
def test_sets_are_ordered_ascending_sequences(name: str) -> None:
    """Ordered tuple, not a `set`: `run_benchmark` consumes seeds positionally.

    The pairing across arms is `seeds[occurrence - 1]`, so the declared order is
    part of the experiment. A `set` has no such order, and a duplicate would make
    one occurrence shadow another.
    """
    seeds = SETS[name]
    assert isinstance(seeds, tuple), f"{name} must be a tuple, got {type(seeds).__name__}"
    assert list(seeds) == sorted(seeds), f"{name} must be declared in ascending order"
    assert len(seeds) == len(set(seeds)), f"{name} declares a duplicate seed"


def test_declared_order_does_not_depend_on_process_hash_seed() -> None:
    """Importing the module must give the same sequences in any interpreter.

    This pins that the declared order is a property of the module rather than of
    the hash salt, so two processes (and therefore two arms, in a future
    parallel run) agree on it. It is not what rules out a `set`: small integer
    hashes are their own values, so a set of contiguous integers happens to
    iterate in the same order in every process. The isinstance check above is
    what actually rules out a `set`.
    """
    code = (
        "from precondition_library.bench.splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS;"
        "print(SMOKE_SEEDS); print(TUNE_SEEDS); print(EVAL_SEEDS)"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": hash_seed, "PATH": "/usr/bin:/bin"},
            check=True,
        ).stdout
        for hash_seed in ("0", "1")
    ]
    assert runs[0] == runs[1]


# --- the roles: which occurrences the two analyses may use -------------------


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_declared_role_counts_are_the_plan_s_arithmetic(name: str, fault: str) -> None:
    """Each set's variant/replay split, as its docstring states it.

    This is the number the report's independence claim depends on, so it is
    asserted rather than described. The variant count is three for every set --
    the injector's declared states -- and a set of any length has the rest as
    replays; a set whose variant count grew would mean a fault gained a state,
    and a set whose replay count grew without the variant count changing is the
    only kind of growth that is free of an independence claim.
    """
    roles = occurrence_roles(SETS[name], fault)
    variants = roles.count(OccurrenceRole.VARIANT)
    replays = roles.count(OccurrenceRole.REPLAY)
    assert (variants, replays) == DECLARED_ROLE_COUNTS[name], (
        f"{name}/{fault}: the set splits {variants} variant(s) and {replays} replay(s), "
        f"but its docstring declares {DECLARED_ROLE_COUNTS[name]}; update the docstring "
        f"and this table together, or the report's arithmetic is unstated"
    )
    assert variants + replays == len(SETS[name]), "every occurrence gets exactly one role"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_every_variant_is_the_first_sight_of_its_resolution(name: str, fault: str) -> None:
    """The rule, not a restatement of it: a variant introduces its resolution.

    A role assigned by position rather than by what the injector will do would
    still pass a count check, so the mapping between the two is asserted: the
    variant occurrences are exactly the first occurrence of each resolution.
    """
    spec = FAULTS[fault]
    roles = occurrence_roles(SETS[name], fault)
    resolutions = [spec.variant_for_seed(seed) for seed in SETS[name]]
    first_sight = []
    seen: set[str | None] = set()
    for resolution in resolutions:
        first_sight.append(
            OccurrenceRole.VARIANT if resolution not in seen else OccurrenceRole.REPLAY
        )
        seen.add(resolution)
    assert list(roles) == first_sight
    assert {r for role, r in zip(roles, resolutions) if role is OccurrenceRole.VARIANT} == set(
        resolutions
    ), "every declared resolution must be introduced by a variant occurrence"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_a_set_long_enough_to_repeat_has_a_replay(name: str, fault: str) -> None:
    """The cost curve can only bend on a replay, so a runnable set needs one.

    A set that never revisits a state produces a flat curve by construction, and
    a flat curve reads like a result rather than like a plan that could not show
    amortization (issue #81).
    """
    assert OccurrenceRole.REPLAY in occurrence_roles(SETS[name], fault), (
        f"{name}/{fault} never revisits a state, so no program can ever be replayed in it"
    )


@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_the_role_keys_on_the_resolution_not_on_the_seed(fault: str) -> None:
    """Two different seeds selecting one state: the second is still a replay.

    This is the rule's whole point. A plan that called a new *seed* independent
    would count the same state's program twice, and `diverged`'s seeds 0 and 4
    (both `overlapping_files`) are the case that made the distinction necessary.
    """
    spec = FAULTS[fault]
    first = next(seed for seed in range(64) if spec.variant_for_seed(seed) is not None)
    resolution = spec.variant_for_seed(first)
    second = next(
        seed for seed in range(64) if seed != first and spec.variant_for_seed(seed) == resolution
    )
    roles = occurrence_roles([first, second], fault)
    assert list(roles) == [OccurrenceRole.VARIANT, OccurrenceRole.REPLAY]
    assert first != second, "the replay is a different seed, not a repeated one"


def test_a_fault_with_no_resolution_mapping_is_refused() -> None:
    """No mapping means no resolution to recur, so a role would be invented.

    `bench.run` refuses these faults before any episode runs, so reaching this
    with one is a caller that skipped that check -- and a row labelled variant or
    replay on no evidence would be a fact about nothing.
    """
    without_mapping = next(
        name for name, spec in sorted(FAULTS.items()) if spec.variant_for_seed(0) is None
    )
    with pytest.raises(ValueError, match="no seed-to-resolution mapping"):
        occurrence_roles([0, 1], without_mapping)
