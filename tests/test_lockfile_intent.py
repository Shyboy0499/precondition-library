"""The lock-conflict intent, defined but not registered (#191, step 3).

`tasks.faults.lockfile_conflict.INTENT` labels each injected state with the resolution
it needs and declares which others the fault's own checker also accepts (ADR-0023). It
is not registered, so nothing measured reads it yet. These tests pin, on real sandboxes:

* it is defined and not registered, and admission still sees one lockfile_conflict state;
* each injected state is labelled as declared, and its declared grid entry matches what
  a real sandbox observes;
* **the declared acceptable sets are exactly what the checker accepts**, by replaying
  every gold body on every state with its conditions stripped;
* each gold program's preconditions fire on its own state and nowhere else, and no
  measured intent labels a lock-conflict state -- `diverged` used to call it `merge`;
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
from precondition_library.tasks.faults.lockfile_conflict import (
    INTENT,
    SPEC,
    STATE_VARIANT,
    state_for_seed,
)
from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK, INTENTS, ambiguous_intents
from precondition_library.tasks.state_grid import LOCKFILE_STATES, STATE_GRID

SEED_FOR = {"additions_only": 0, "upstream_removed": 5, "local_removed": 2}
VARIANTS = ("take_upstream", "keep_local")
DECISION_FIELDS = (
    "upstream_ahead",
    "upstream_behind",
    "merge_conflicted_files",
    "upstream_dropped_lines",
    "local_dropped_lines",
)


def _gold(variant: str):
    return next(p for p in gold_programs(INTENT.name) if p.variant == variant)


def test_the_intent_is_defined_but_not_registered() -> None:
    assert INTENT.name not in INTENTS and INTENT.name not in STATE_GRID
    assert "lockfile_conflict" in EXCLUDED_FROM_BENCHMARK
    assert SPEC.variant_for_seed(0) is None, "admission still builds one lockfile_conflict state"
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(SEED_FOR)


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_each_injected_state_is_labelled_as_declared(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["lockfile_conflict"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    label = INTENT.correct_variant(observed)
    assert label is not None and label.id == STATE_VARIANT[state]
    declared = LOCKFILE_STATES[state]
    for field in DECISION_FIELDS:
        assert getattr(observed, field) == getattr(declared, field), field


def test_the_benign_state_needs_nothing() -> None:
    benign = LOCKFILE_STATES["benign_nothing_local"]
    assert INTENT.correct_variant(benign) is None
    assert INTENT.acceptable_variants(benign) == ()


def test_every_resolution_labels_some_state() -> None:
    labels = {INTENT.correct_variant(s) for s in LOCKFILE_STATES.values()} - {None}
    assert {variant.id for variant in labels} == set(VARIANTS)


@pytest.mark.parametrize(
    ("state", "variant"), [(state, variant) for state in sorted(SEED_FOR) for variant in VARIANTS]
)
def test_the_declared_set_is_what_the_checker_accepts(state: str, variant: str) -> None:
    body_only = _gold(variant).model_copy(update={"preconditions": [], "postconditions": []})
    box = build_sandbox(SEED_FOR[state], ["lockfile_conflict"])
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
    states = LOCKFILE_STATES
    assert INTENT.acceptable_variants(states["additions_only"]) == ("keep_local", "take_upstream")
    assert INTENT.acceptable_variants(states["upstream_removed"]) == ("take_upstream",)
    assert INTENT.acceptable_variants(states["local_removed"]) == ("keep_local",)


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_gold_preconditions_fire_on_their_own_state_only(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["lockfile_conflict"])
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
    box = build_sandbox(SEED_FOR[state], ["lockfile_conflict"])
    try:
        result = replay(_gold(STATE_VARIANT[state]), box)
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert result.ok, result.reason
    assert verdict.ok, verdict.detail


@pytest.mark.parametrize("state", sorted(LOCKFILE_STATES))
def test_no_measured_intent_labels_a_lock_conflict_state(state: str) -> None:
    for intent in ambiguous_intents():
        assert intent.correct_variant(LOCKFILE_STATES[state]) is None, intent.name
        assert intent.acceptable_variants(LOCKFILE_STATES[state]) == (), intent.name


def test_no_phrasing_names_a_resolution() -> None:
    texts = [*INTENT.phrasings, *(p for ps in INTENT.variant_phrasings.values() for p in ps)]
    for text in texts:
        for variant in VARIANTS:
            first, second = variant.split("_")
            pattern = rf"\b{first}[ _]+{second}\b"
            assert not re.search(pattern, text, re.IGNORECASE), (variant, text)


def test_few_requests_name_the_fault() -> None:
    assert INTENT.naming_fraction(range(200)) <= 0.35
