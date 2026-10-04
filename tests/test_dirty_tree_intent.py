"""The dirty-tree intent, defined but not registered (#189, step 3).

`tasks.faults.dirty_tree.INTENT` labels each injected state with the resolution it
needs and declares which others the fault's own checker also accepts (ADR-0023). It is
not registered, so nothing measured reads it yet. These tests pin, on real sandboxes:

* it is defined and not registered, and admission still sees one dirty_tree state;
* each injected state is labelled as declared, and its declared grid entry matches what
  a real sandbox observes;
* **the declared acceptable sets are exactly what the checker accepts**, by replaying
  every gold body on every state with its conditions stripped;
* each gold program's preconditions fire on its own state and nowhere else;
* no phrasing names a resolution.
"""

from __future__ import annotations

import re

import pytest
from conftest import gold_programs

from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.runtime.replay import replay
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.dirty_tree import INTENT, SPEC, STATE_VARIANT, state_for_seed
from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK, INTENTS
from precondition_library.tasks.state_grid import DIRTY_TREE_STATES, STATE_GRID

SEED_FOR = {"disjoint": 5, "same_file": 0, "collision": 2}
VARIANTS = ("stash", "commit", "aside")
DECISION_FIELDS = (
    "dirty_worktree",
    "upstream_ahead",
    "upstream_behind",
    "dirty_files",
    "untracked_upstream_collisions",
    "upstream_touched_files",
)


def _gold(variant: str):
    return next(p for p in gold_programs(INTENT.name) if p.variant == variant)


def test_the_intent_is_defined_but_not_registered() -> None:
    assert INTENT.name not in INTENTS and INTENT.name not in STATE_GRID
    assert "dirty_tree" in EXCLUDED_FROM_BENCHMARK
    assert SPEC.variant_for_seed(0) is None, "admission still builds one dirty_tree state"
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(SEED_FOR)


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_each_injected_state_is_labelled_as_declared(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["dirty_tree"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    label = INTENT.correct_variant(observed)
    assert label is not None and label.id == STATE_VARIANT[state]
    declared = DIRTY_TREE_STATES[state]
    for field in DECISION_FIELDS:
        assert getattr(observed, field) == getattr(declared, field), field


def test_the_benign_state_needs_nothing() -> None:
    benign = DIRTY_TREE_STATES["benign_clean"]
    assert INTENT.correct_variant(benign) is None
    assert INTENT.acceptable_variants(benign) == ()


def test_every_resolution_labels_some_state() -> None:
    labels = {INTENT.correct_variant(s) for s in DIRTY_TREE_STATES.values()} - {None}
    assert {variant.id for variant in labels} == set(VARIANTS)


@pytest.mark.parametrize(
    ("state", "variant"), [(state, variant) for state in sorted(SEED_FOR) for variant in VARIANTS]
)
def test_the_declared_set_is_what_the_checker_accepts(state: str, variant: str) -> None:
    body_only = _gold(variant).model_copy(update={"preconditions": [], "postconditions": []})
    box = build_sandbox(SEED_FOR[state], ["dirty_tree"])
    try:
        acceptable = INTENT.acceptable_variants(StateFingerprint.observe(box))
        replay(body_only, box)
        passes = SPEC.check(box).ok
    finally:
        box.destroy()
    assert passes == (variant in acceptable), (
        f"{state}: the checker {'accepts' if passes else 'rejects'} {variant!r}, but the "
        f"declared acceptable set is {acceptable}"
    )


def test_the_measured_shape() -> None:
    """Stated directly, so a reader need not run the replay to see it."""
    assert INTENT.acceptable_variants(DIRTY_TREE_STATES["disjoint"]) == ("aside", "commit", "stash")
    assert INTENT.acceptable_variants(DIRTY_TREE_STATES["same_file"]) == (
        "aside",
        "commit",
        "stash",
    )
    assert INTENT.acceptable_variants(DIRTY_TREE_STATES["collision"]) == ("aside",)


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_gold_preconditions_fire_on_their_own_state_only(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["dirty_tree"])
    try:
        fired = sorted(
            p.variant for p in gold_programs(INTENT.name) if evaluate_preconditions(p, box).ok
        )
    finally:
        box.destroy()
    assert fired == [STATE_VARIANT[state]]


def test_gold_fires_on_nothing_in_a_clean_sandbox() -> None:
    box = build_sandbox(0, [])
    try:
        fired = [p.id for p in gold_programs(INTENT.name) if evaluate_preconditions(p, box).ok]
    finally:
        box.destroy()
    assert fired == []


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_each_gold_program_resolves_its_own_state_with_its_conditions(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["dirty_tree"])
    try:
        result = replay(_gold(STATE_VARIANT[state]), box)
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert result.ok, result.reason
    assert verdict.ok, verdict.detail


def test_no_phrasing_names_a_resolution() -> None:
    texts = [*INTENT.phrasings, *(p for ps in INTENT.variant_phrasings.values() for p in ps)]
    for text in texts:
        for variant in VARIANTS:
            assert not re.search(rf"\b{variant}\b", text, re.IGNORECASE), (variant, text)
