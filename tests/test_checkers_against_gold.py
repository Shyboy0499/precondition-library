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

from precondition_library.tasks import ALL_FAULTS


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
