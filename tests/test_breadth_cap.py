"""A precondition set that fires on too much of the state universe is rejected (#10).

#10 asks for a "measured breadth cap: predicates matching >X% of sampled states
are rejected, and X plus the sampling procedure are recorded." X is
`compile.BREADTH_CAP` (0.50) and the procedure is `compile.sampled_states` -- the
clean sandbox plus one sandbox per distinct injected state of every fault.

These tests pin three things against real sandboxes: a well-targeted (gold)
program fires on one sampled state, so the breadth measurement is grounded; an
over-broad precondition set measures over the cap and is refused by admission;
and the cheap breadth count `admit` uses agrees with the standalone
`precondition_breadth`, so the enforced number and the recorded number are one.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.agents.compile import (
    BREADTH_CAP,
    admit,
    precondition_breadth,
    sampled_states,
)
from precondition_library.program import Predicate


def test_the_universe_is_clean_plus_every_faults_distinct_states() -> None:
    universe = sampled_states()
    assert universe[0] == ("", 0), "the clean sandbox is first"
    assert len(universe) == 14, (
        "clean + 3 each for diverged, submodule, dirty_tree and branch_renamed + 1 single-state"
    )
    # No duplicate (fault, seed) entries -- each sampled state is distinct.
    assert len(set(universe)) == len(universe)


@pytest.mark.parametrize(
    "intent",
    [
        "sync_fork_with_upstream",
        "restore_submodule_state",
        "keep_uncommitted_work_and_sync",
        "follow_renamed_upstream_branch",
    ],
)
def test_a_gold_program_fires_on_exactly_its_own_state(intent: str) -> None:
    """Each gold resolution matches one sampled state -- its own -- so breadth is 1/14."""
    for program in gold_programs(intent):
        fired, total, where = precondition_breadth(program)
        assert total == 14
        assert fired == 1, f"{program.id} fired on {where}, expected only its own state"
        assert fired <= BREADTH_CAP * total


def test_an_over_broad_precondition_is_measured_over_cap_and_refused() -> None:
    """A precondition that holds everywhere fires on the whole universe and is refused.

    `true` holds in every sandbox, so the set matches all fourteen sampled states --
    far over the cap. The measurement sees that, and admission refuses the program
    (here on the clean-sandbox class, which is the sharpest reason; the breadth cap
    is the holistic backstop behind it).
    """
    program = gold_programs("sync_fork_with_upstream")[0].model_copy(
        update={
            "preconditions": [Predicate(name="always", description="holds anywhere", probe="true")]
        }
    )
    fired, total, _where = precondition_breadth(program)
    assert fired == total == 14
    assert fired > BREADTH_CAP * total

    admitted, reason = admit(program, "diverged", seeds=[1])
    assert not admitted and reason


def test_admit_records_the_breadth_it_enforces() -> None:
    """The admitted reason quotes the same fraction the standalone measurement gives."""
    program = gold_programs("sync_fork_with_upstream")[0]  # discard
    fired, total, _ = precondition_breadth(program)
    admitted, reason = admit(program, "diverged", seeds=[1])
    assert admitted, reason
    assert f"fired on {fired} of {total} sampled states" in reason
