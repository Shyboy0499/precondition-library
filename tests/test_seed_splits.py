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

#: (variant occurrences, replay occurrences) per (set, fault), as the plan's own
#: arithmetic now stands after ADR-0005 keyed the role on **instance identity**.
#: A variant is the first sight of an *instance*, not of a resolution, so the
#: counts are no longer three per family: the axis draw makes most seeds a new
#: environment. The smoke set's four seeds all draw distinct instances, so it has
#: no replay left -- the honest cost of the change, recorded here rather than
#: hidden; tune and eval keep enough replays for the cost curve.
DECLARED_ROLE_COUNTS = {
    ("smoke", "diverged"): (4, 0),
    ("smoke", "submodule_moved"): (4, 0),
    ("tune", "diverged"): (15, 1),
    ("tune", "submodule_moved"): (7, 9),
    ("eval", "diverged"): (32, 8),
    ("eval", "submodule_moved"): (15, 25),
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
    """Each set's variant/replay split, as the plan's own arithmetic states it.

    This is the number the report's independence claim depends on, so it is
    asserted rather than described. ADR-0005 keyed the role on **instance
    identity**, so a variant is the first sight of an *instance* and the counts
    differ by set and by fault -- they are no longer "three per family". The
    smoke set draws four distinct instances over its four seeds and so has no
    replay; tune and eval do, which is what the cost curve needs.
    """
    roles = occurrence_roles(SETS[name], fault)
    variants = roles.count(OccurrenceRole.VARIANT)
    replays = roles.count(OccurrenceRole.REPLAY)
    assert (variants, replays) == DECLARED_ROLE_COUNTS[(name, fault)], (
        f"{name}/{fault}: the set splits {variants} variant(s) and {replays} replay(s), "
        f"but the plan declares {DECLARED_ROLE_COUNTS[(name, fault)]}; update the "
        f"docstring and this table together, or the report's arithmetic is unstated"
    )
    assert variants + replays == len(SETS[name]), "every occurrence gets exactly one role"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_every_variant_is_the_first_sight_of_its_instance(name: str, fault: str) -> None:
    """The rule, not a restatement of it: a variant introduces its instance.

    A role assigned by position rather than by what the injector will do would
    still pass a count check, so the mapping between the two is asserted: the
    variant occurrences are exactly the first occurrence of each *instance*
    identity (ADR-0005 decision 5), not of each resolution.
    """
    spec = FAULTS[fault]
    roles = occurrence_roles(SETS[name], fault)
    instances = [spec.instance_for_seed(seed) for seed in SETS[name]]
    first_sight = []
    seen: set[str | None] = set()
    for instance in instances:
        first_sight.append(
            OccurrenceRole.VARIANT if instance not in seen else OccurrenceRole.REPLAY
        )
        seen.add(instance)
    assert list(roles) == first_sight
    assert {r for role, r in zip(roles, instances) if role is OccurrenceRole.VARIANT} == set(
        instances
    ), "every declared instance must be introduced by a variant occurrence"


@pytest.mark.parametrize("name", sorted(SETS))
@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_a_set_long_enough_to_repeat_has_a_replay(name: str, fault: str) -> None:
    """The cost curve can only bend on a replay, so a set it is read from needs one.

    A set that never revisits an instance produces a flat curve by construction,
    and a flat curve reads like a result rather than like a plan that could not
    show amortization (issue #81). The smoke set is the exception and says so:
    its four seeds draw four distinct instances after ADR-0005, so it has no
    replay and is a wiring check rather than a source of a cost curve.
    """
    roles = occurrence_roles(SETS[name], fault)
    if name == "smoke":
        assert OccurrenceRole.REPLAY not in roles, (
            f"smoke/{fault} now revisits an instance; if that is deliberate, update "
            f"the plan's arithmetic and this exception"
        )
    else:
        assert OccurrenceRole.REPLAY in roles, (
            f"{name}/{fault} never revisits an instance, so no program can ever be replayed in it"
        )


@pytest.mark.parametrize("fault", MEASURABLE_FAULTS)
def test_the_role_keys_on_the_instance_not_on_the_resolution(fault: str) -> None:
    """One resolution, two instances: both occurrences are independent variants.

    This is the rule's whole point after ADR-0005. Before it, a second seed
    selecting one resolution was labelled a replay because the two environments
    were identical; now the axis draw makes it a new environment, so calling it a
    replay would discard a real independent observation. `diverged`'s seeds 0 and
    4 (both `overlapping_files`) are the case that made the distinction
    necessary, and they now draw different instances.
    """
    spec = FAULTS[fault]
    first = next(seed for seed in range(256) if spec.variant_for_seed(seed) is not None)
    resolution = spec.variant_for_seed(first)
    first_instance = spec.instance_for_seed(first)
    second = next(
        seed
        for seed in range(256)
        if seed != first
        and spec.variant_for_seed(seed) == resolution
        and spec.instance_for_seed(seed) != first_instance
    )
    roles = occurrence_roles([first, second], fault)
    assert list(roles) == [OccurrenceRole.VARIANT, OccurrenceRole.VARIANT], (
        "two seeds on different instances of one resolution are two independent "
        "environments, not a variant and a replay"
    )
    # The converse: two seeds on one instance really are a variant and a replay.
    repeat = next(
        seed
        for seed in range(256)
        if seed != first and spec.instance_for_seed(seed) == first_instance
    )
    assert list(occurrence_roles([first, repeat], fault)) == [
        OccurrenceRole.VARIANT,
        OccurrenceRole.REPLAY,
    ]


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
