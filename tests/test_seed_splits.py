"""The seed plan's properties, which are the whole reason it is a module.

The split is the experiment's integrity property: tuning on a seed that later
appears in the evaluation set contaminates the result, and a split chosen after
seeing scores is not a split. These tests exist so the plan cannot regress into
something that merely looks like one -- overlap, a non-integer seed, an empty
set, or a `set` whose iteration order is not declared.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from precondition_library.bench.splits import EVAL_SEEDS, SMOKE_SEEDS, TUNE_SEEDS

SETS = {
    "smoke": SMOKE_SEEDS,
    "tune": TUNE_SEEDS,
    "eval": EVAL_SEEDS,
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
