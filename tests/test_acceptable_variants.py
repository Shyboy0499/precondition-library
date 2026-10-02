"""Each state's acceptable resolutions are exactly the ones its checker accepts (#172).

A state's label names one canonical resolution. Its acceptable set names every
resolution the fault's own checker passes there (ADR-0023), and a fire is a mismatch
only outside that set. The set is a declaration (`ResolutionVariant.accepted_by`), so
this test holds it to the checker: every gold resolution's body is replayed on every
injected state, with its pre- and postconditions stripped so nothing refuses, and the
checker's verdict must equal membership in the declared set. A declaration wider than
the checker would excuse a fire that leaves the repository wrong; a narrower one would
count a working resolution as a mismatch, which is what #172 found.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.runtime.replay import replay
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import ambiguous_intents

INTENTS = {intent.fault: intent for intent in ambiguous_intents()}


def _first_seed_per_state(fault: str) -> dict[str, int]:
    seeds: dict[str, int] = {}
    spec = FAULTS[fault]
    for seed in range(200):
        state = spec.variant_for_seed(seed)
        if state is not None:
            seeds.setdefault(state, seed)
    return seeds


CASES = [
    (fault, state, seed, program.variant)
    for fault, intent in sorted(INTENTS.items())
    for state, seed in sorted(_first_seed_per_state(fault).items())
    for program in gold_programs(intent.name)
]


@pytest.mark.parametrize(("fault", "state", "seed", "variant"), CASES)
def test_the_declared_set_is_what_the_checker_accepts(fault, state, seed, variant) -> None:
    intent = INTENTS[fault]
    gold = next(p for p in gold_programs(intent.name) if p.variant == variant)
    body_only = gold.model_copy(update={"preconditions": [], "postconditions": []})

    box = build_sandbox(seed, [fault])
    try:
        acceptable = intent.acceptable_variants(StateFingerprint.observe(box))
        replay(body_only, box)
        passes = FAULTS[fault].check(box).ok
    finally:
        box.destroy()

    assert passes == (variant in acceptable), (
        f"{fault} {state} (seed {seed}): the checker {'accepts' if passes else 'rejects'} "
        f"{variant!r}, but the declared acceptable set is {acceptable}"
    )


def test_the_label_is_always_acceptable_and_negatives_accept_nothing(state_grid) -> None:
    for intent in ambiguous_intents():
        for state in state_grid[intent.name].values():
            label = intent.correct_variant(state)
            acceptable = intent.acceptable_variants(state)
            if label is None:
                assert acceptable == ()
            else:
                assert label.id in acceptable


def test_diverged_accepts_merge_and_rebase_everywhere_and_discard_only_where_labelled(
    state_grid,
) -> None:
    """The measured shape of #172, stated directly so a reader need not run the replay."""
    sync = next(i for i in ambiguous_intents() if i.fault == "diverged")
    grid = state_grid["sync_fork_with_upstream"]
    assert sync.acceptable_variants(grid["empty_local_commits"]) == ("discard", "merge", "rebase")
    assert sync.acceptable_variants(grid["overlapping_files"]) == ("merge", "rebase")
    assert sync.acceptable_variants(grid["disjoint_files"]) == ("merge", "rebase")
    assert sync.acceptable_variants(grid["benign_nothing_local"]) == ()
