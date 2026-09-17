"""Gold resolutions must be well-formed, and must exist for every resolution.

These are the >=2 candidates issue #3 asks for, written by hand because the
compile step (issue #4) does not exist yet. Gold-first is a rule here, not a
convenience: a benchmark whose checkers are wrong reports plausible numbers that
mean nothing.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.agents.compile import admit
from precondition_library.program import ProgramStatus
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.registry import ambiguous_intents


def _seed_selecting(fault: str, variant: str) -> int:
    """The first seed whose injector selects `variant` for `fault`.

    Read through `FaultSpec.variant_for_seed`, the same mapping `inject` uses, so
    the positive sandbox really is the state the program implements.
    """
    spec = FAULTS[fault]
    for seed in range(64):
        if spec.variant_for_seed(seed) == variant:
            return seed
    raise AssertionError(f"{fault}: no seed in 0..63 selects {variant!r}")


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_every_ambiguous_intent_has_gold_programs(intent: str) -> None:
    programs = gold_programs(intent)
    assert len(programs) >= 2, "an ambiguous intent needs at least two candidates"


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_covers_every_declared_resolution(intent: str) -> None:
    declared = {v.id for spec in ambiguous_intents() if spec.name == intent for v in spec.variants}
    assert {program.variant for program in gold_programs(intent)} == declared


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_programs_are_well_formed(intent: str) -> None:
    for program in gold_programs(intent):
        assert program.intent == intent
        assert program.status is ProgramStatus.CANDIDATE, "hand-written != admitted"
        assert program.preconditions, f"{program.id}: needs preconditions"
        assert program.postconditions, f"{program.id}: needs postconditions"
        assert program.body.strip(), f"{program.id}: needs a body"
        for predicate in program.preconditions + program.postconditions:
            assert predicate.probe.strip(), f"{program.id}: {predicate.name} has an empty probe"
            assert predicate.description.strip(), f"{program.id}: {predicate.name} undescribed"


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_bodies_are_distinct(intent: str) -> None:
    """Two candidates that do the same thing are not two resolutions."""
    bodies = {p.body.strip() for p in gold_programs(intent)}
    assert len(bodies) == len(gold_programs(intent))


@pytest.mark.parametrize("intent", [i.name for i in ambiguous_intents()])
def test_gold_provenance_says_hand_written(intent: str) -> None:
    for program in gold_programs(intent):
        assert "hand-written" in program.provenance.compiled_from_task
        assert program.provenance.compiler_version == "human"


@pytest.mark.parametrize("intent", ambiguous_intents(), ids=lambda spec: spec.name)
def test_gold_programs_are_admitted(intent, repository_unchanged) -> None:
    """The hand-written reference programs clear the two-sided gate.

    Gold-first: if the gate cannot admit the artifacts written by hand for every
    declared resolution, it is not measuring what the benchmark needs. The merge
    gold originally accepted the unrelated lockfile-conflict sandbox as well as
    the diverged overlap it is for -- the fingerprint cannot tell the two apart by
    overlap alone -- so its preconditions were tightened (see the program's YAML);
    weakening the gate was not an option.
    """
    for program in gold_programs(intent.name):
        seed = _seed_selecting(intent.fault, program.variant)
        admitted, reason = admit(program, intent.fault, seeds=[seed])
        assert admitted, f"{program.id}: {reason}"
