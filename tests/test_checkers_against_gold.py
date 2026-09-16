"""Prove the ground-truth checkers are correct before letting an agent near them.

A benchmark whose checker is wrong reports plausible numbers that mean nothing.
So each fault ships with a hand-written gold solution, and the checker must
accept it. A failure here means the checker is broken — not the agent — and no
episode result should be trusted until this passes.

The reverse direction matters too: a checker must reject an environment that has
merely been *left alone*, otherwise every arm scores 100%.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.program import Program
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.runtime.replay import replay
from precondition_library.tasks import ALL_FAULTS
from precondition_library.tasks.faults.submodule_moved import SPEC as SUBMODULE_MOVED
from precondition_library.tasks.faults.submodule_moved import state_for_seed

# Loaded at import so the parametrisation below follows the committed file: a
# fourth resolution added to the yaml is exercised without editing this test.
SUBMODULE_PROGRAMS = gold_programs("restore_submodule_state")


def _seed_for_variant(variant: str | None) -> int:
    """A seed whose `submodule_moved` injection is `variant`, or fail loudly."""
    for seed in range(64):
        if state_for_seed(seed) == variant:
            return seed
    raise AssertionError(f"no seed in 0..63 injects {variant!r}")


@pytest.mark.parametrize("program", SUBMODULE_PROGRAMS, ids=lambda program: program.variant)
def test_submodule_gold_body_satisfies_its_checker(program: Program, make_sandbox) -> None:
    """Run each committed `restore_submodule_state` body against its own state.

    The rule this file exists for, applied to the one intent that never had it:
    the body executes in a real sandbox, and the fault's checker -- the thing the
    whole benchmark grades against -- must accept the outcome. A gold program that
    only satisfied its own postconditions would still be measuring the program
    against itself; this is the checker agreeing.

    Parametrised over the committed gold file, not over the three ids, so a fourth
    resolution cannot be added without a body that runs here.
    """
    box = make_sandbox(_seed_for_variant(program.variant), ["submodule_moved"])

    preconditions = evaluate_preconditions(program, box)
    assert preconditions.ok, (
        f"{program.id}: gold body fired on its own state: {preconditions.detail}"
    )

    result = replay(program, box)
    assert result.ok, f"{program.id}: body or postconditions failed: {result.reason}"

    verdict = SUBMODULE_MOVED.check(box)
    assert verdict.ok, f"{program.id}: checker rejected its own gold: {verdict.detail}"


@pytest.mark.skip(
    reason="gold exists for two of five faults and this loops every fault; "
    "restricting it to the intents that have gold is issue #9's negative controls"
)
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_checker_accepts_gold_solution(fault_type: str) -> None:
    raise NotImplementedError


@pytest.mark.skip(
    reason="gold exists for two of five faults and this loops every fault; "
    "restricting it to the intents that have gold is issue #9's negative controls"
)
@pytest.mark.parametrize("fault_type", ALL_FAULTS)
def test_checker_rejects_untouched_sandbox(fault_type: str) -> None:
    """The injected fault must be the only reason the checker can pass."""
    raise NotImplementedError
