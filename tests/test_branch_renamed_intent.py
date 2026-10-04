"""The renamed-branch intent, registered and measured (#190, ADR-0028).

`tasks.faults.branch_renamed.INTENT` labels each injected state with the resolution it
needs and declares which others the fault's own checker also accepts (ADR-0023). It is
registered, so every measured path reads it. These tests pin, on real sandboxes:

* it is registered, its fault is no longer excluded, and each seed is labelled with the
  resolution its state needs;
* each injected state is labelled as declared, and its declared grid entry matches what
  a real sandbox observes;
* **the declared acceptable sets are exactly what the checker accepts**, by replaying
  every gold body on every state with its conditions stripped;
* each gold program's preconditions fire on its own state and nowhere else, and no
  other measured intent labels a renamed state;
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
from precondition_library.tasks.faults.branch_renamed import (
    INTENT,
    SPEC,
    STATE_VARIANT,
    state_for_seed,
)
from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK, INTENTS, ambiguous_intents
from precondition_library.tasks.state_grid import BRANCH_RENAMED_STATES, STATE_GRID

SEED_FOR = {"plain": 0, "local_work": 1, "name_taken": 6}
VARIANTS = ("rename", "retrack", "merge")
DECISION_FIELDS = (
    "upstream_ahead",
    "upstream_behind",
    "tracked_branch",
    "upstream_default_branch",
    "local_branches",
    "branch",
)


def _gold(variant: str):
    return next(p for p in gold_programs(INTENT.name) if p.variant == variant)


def test_the_intent_is_registered_and_measured() -> None:
    assert INTENTS[INTENT.name] is INTENT and STATE_GRID[INTENT.name] is BRANCH_RENAMED_STATES
    assert INTENT in ambiguous_intents()
    assert "branch_renamed" not in EXCLUDED_FROM_BENCHMARK
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(SEED_FOR)
    for state, seed in SEED_FOR.items():
        assert SPEC.variant_for_seed(seed) == STATE_VARIANT[state], state


def test_the_request_is_a_phrasing_not_a_fixed_sentence() -> None:
    texts = {SPEC.task_text(seed) for seed in range(40)}
    assert texts <= set(INTENT.phrasings) and len(texts) > 1


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_each_injected_state_is_labelled_as_declared(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["branch_renamed"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    label = INTENT.correct_variant(observed)
    assert label is not None and label.id == STATE_VARIANT[state]
    declared = BRANCH_RENAMED_STATES[state]
    for field in DECISION_FIELDS:
        assert getattr(observed, field) == getattr(declared, field), field


def test_the_benign_state_needs_nothing() -> None:
    benign = BRANCH_RENAMED_STATES["benign_not_renamed"]
    assert INTENT.correct_variant(benign) is None
    assert INTENT.acceptable_variants(benign) == ()


def test_a_clone_that_records_no_upstream_default_is_not_renamed(make_sandbox) -> None:
    """Every state no rename touched records none, so the rules must not fire there."""
    observed = StateFingerprint.observe(make_sandbox(0, []))
    assert observed.upstream_default_branch == ""
    assert INTENT.correct_variant(observed) is None


def test_every_resolution_labels_some_state() -> None:
    labels = {INTENT.correct_variant(s) for s in BRANCH_RENAMED_STATES.values()} - {None}
    assert {variant.id for variant in labels} == set(VARIANTS)


@pytest.mark.parametrize(
    ("state", "variant"), [(state, variant) for state in sorted(SEED_FOR) for variant in VARIANTS]
)
def test_the_declared_set_is_what_the_checker_accepts(state: str, variant: str) -> None:
    body_only = _gold(variant).model_copy(update={"preconditions": [], "postconditions": []})
    box = build_sandbox(SEED_FOR[state], ["branch_renamed"])
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
    states = BRANCH_RENAMED_STATES
    assert INTENT.acceptable_variants(states["plain"]) == ("merge", "rename", "retrack")
    assert INTENT.acceptable_variants(states["local_work"]) == ("merge",)
    assert INTENT.acceptable_variants(states["name_taken"]) == ("merge", "retrack")


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_gold_preconditions_fire_on_their_own_state_only(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["branch_renamed"])
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
    box = build_sandbox(SEED_FOR[state], ["branch_renamed"])
    try:
        result = replay(_gold(STATE_VARIANT[state]), box)
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert result.ok, result.reason
    assert verdict.ok, verdict.detail


@pytest.mark.parametrize("state", sorted(BRANCH_RENAMED_STATES))
def test_no_measured_intent_labels_a_renamed_state(state: str) -> None:
    """A rename is not another family's situation: their resolutions leave the wiring stale."""
    for intent in ambiguous_intents():
        if intent is INTENT:
            continue
        assert intent.correct_variant(BRANCH_RENAMED_STATES[state]) is None, intent.name
        assert intent.acceptable_variants(BRANCH_RENAMED_STATES[state]) == (), intent.name


def test_no_phrasing_names_a_resolution() -> None:
    texts = [*INTENT.phrasings, *(p for ps in INTENT.variant_phrasings.values() for p in ps)]
    for text in texts:
        for variant in VARIANTS:
            assert not re.search(rf"\b{variant}\b", text, re.IGNORECASE), (variant, text)


def test_few_requests_name_the_fault() -> None:
    assert INTENT.naming_fraction(range(200)) <= 0.35
