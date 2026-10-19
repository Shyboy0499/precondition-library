"""The renamed-config-key family, the first whose state is files, not git history (#266, ADR-0041).

`tasks.faults.config_renamed` injects one of three states into the app's config tree and
labels each with the resolution its own checker needs. These tests pin, on real sandboxes:

* the intent is registered and measured, and each seed is labelled with its state's
  resolution;
* each injected state is labelled as declared, and its grid entry matches what a real
  sandbox observes;
* **the declared acceptable sets are exactly what the checker accepts**, by replaying every
  gold body on every state with its conditions stripped;
* each gold program's preconditions fire on its own state and nowhere else, no other
  measured intent labels a config state, and this intent labels no other family's state;
* the checker refuses each obvious wrong fix;
* no state before this family renders differently (`as_text` leaves the fields out when empty).
"""

from __future__ import annotations

import re
import subprocess

import pytest
from conftest import gold_programs

from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import run_env
from precondition_library.signatures import StateFingerprint, config_assignments
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.config_renamed import (
    AXES,
    INTENT,
    LOCAL_FILE,
    RENAMES,
    SETTINGS_FILE,
    SPEC,
    STATE_VARIANT,
    draw_for_seed,
    state_for_seed,
)
from precondition_library.tasks.registry import EXCLUDED_FROM_BENCHMARK, INTENTS, ambiguous_intents
from precondition_library.tasks.state_grid import CONFIG_RENAMED_STATES, STATE_GRID

SEED_FOR = {"stale_key": 0, "both_keys": 23, "local_override": 14}
"""A seed for each state whose stale key is `timeout_s`, the key the grid declares."""
VARIANTS = ("rename", "drop_old", "migrate_local")
DECISION_FIELDS = (
    "upstream_ahead",
    "upstream_behind",
    "config_stale_keys",
    "config_keys_set_twice",
    "config_ignored_files",
)


def _gold(variant: str):
    return next(p for p in gold_programs(INTENT.name) if p.variant == variant)


def test_the_intent_is_registered_and_measured() -> None:
    assert INTENTS[INTENT.name] is INTENT and STATE_GRID[INTENT.name] is CONFIG_RENAMED_STATES
    assert INTENT in ambiguous_intents()
    assert "config_renamed" not in EXCLUDED_FROM_BENCHMARK
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(SEED_FOR)
    for state, seed in SEED_FOR.items():
        assert SPEC.variant_for_seed(seed) == STATE_VARIANT[state], state
        assert draw_for_seed(seed).old == "timeout_s", state


def test_the_request_is_a_phrasing_not_a_fixed_sentence() -> None:
    texts = {SPEC.task_text(seed) for seed in range(40)}
    assert texts <= set(INTENT.phrasings) and len(texts) > 1


def test_every_key_is_drawn_under_every_resolution() -> None:
    """The `key` axis is what exposes a program that hard-codes the key it learned on."""
    drawn = {(draw_for_seed(s).old, draw_for_seed(s).resolution) for s in range(2000, 2200)}
    assert drawn == {(old, variant) for old in AXES["key"] for variant in VARIANTS}


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_each_injected_state_is_labelled_as_declared(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["config_renamed"])
    try:
        observed = StateFingerprint.observe(box)
    finally:
        box.destroy()
    label = INTENT.correct_variant(observed)
    assert label is not None and label.id == STATE_VARIANT[state]
    declared = CONFIG_RENAMED_STATES[state]
    for field in DECISION_FIELDS:
        assert getattr(observed, field) == getattr(declared, field), field
    assert not observed.dirty_worktree, "an ignored override is not a dirty tree"


def test_the_benign_state_needs_nothing() -> None:
    benign = CONFIG_RENAMED_STATES["benign_current"]
    assert INTENT.correct_variant(benign) is None
    assert INTENT.acceptable_variants(benign) == ()


def test_every_resolution_labels_some_state() -> None:
    labels = {INTENT.correct_variant(s) for s in CONFIG_RENAMED_STATES.values()} - {None}
    assert {variant.id for variant in labels} == set(VARIANTS)


@pytest.mark.parametrize(
    ("state", "variant"), [(state, variant) for state in sorted(SEED_FOR) for variant in VARIANTS]
)
def test_the_declared_set_is_what_the_checker_accepts(state: str, variant: str) -> None:
    body_only = _gold(variant).model_copy(update={"preconditions": [], "postconditions": []})
    box = build_sandbox(SEED_FOR[state], ["config_renamed"])
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
    """Stated directly: each state accepts exactly its own resolution."""
    states = CONFIG_RENAMED_STATES
    assert INTENT.acceptable_variants(states["stale_key"]) == ("rename",)
    assert INTENT.acceptable_variants(states["both_keys"]) == ("drop_old",)
    assert INTENT.acceptable_variants(states["local_override"]) == ("migrate_local",)


@pytest.mark.parametrize("state", sorted(SEED_FOR))
def test_gold_preconditions_fire_on_their_own_state_only(state: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["config_renamed"])
    try:
        fired = sorted(
            p.variant for p in gold_programs(INTENT.name) if evaluate_preconditions(p, box).ok
        )
    finally:
        box.destroy()
    assert fired == [STATE_VARIANT[state]]


@pytest.mark.parametrize("seed", [2000, 2001, 2002, 2003, 2004, 2005])
def test_gold_resolves_every_key_not_only_the_one_it_was_written_against(seed: int) -> None:
    box = build_sandbox(seed, ["config_renamed"])
    try:
        result = replay(_gold(SPEC.variant_for_seed(seed)), box)
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert result.ok, result.reason
    assert verdict.ok, verdict.detail


def test_gold_fires_on_nothing_in_a_clean_sandbox() -> None:
    box = build_sandbox(0, [])
    try:
        fired = [p.id for p in gold_programs(INTENT.name) if evaluate_preconditions(p, box).ok]
    finally:
        box.destroy()
    assert fired == []


@pytest.mark.parametrize("state", sorted(CONFIG_RENAMED_STATES))
def test_no_other_measured_intent_labels_a_config_state(state: str) -> None:
    for intent in ambiguous_intents():
        if intent is INTENT:
            continue
        assert intent.correct_variant(CONFIG_RENAMED_STATES[state]) is None, intent.name
        assert intent.acceptable_variants(CONFIG_RENAMED_STATES[state]) == (), intent.name


def test_this_intent_labels_no_other_familys_state() -> None:
    for name, states in STATE_GRID.items():
        if name == INTENT.name:
            continue
        for state, fingerprint in states.items():
            assert INTENT.correct_variant(fingerprint) is None, (name, state)


def _fix(box, command: str) -> None:
    """Apply a hand-written fix, as an agent's shell would."""
    subprocess.run(["bash", "-c", command], cwd=box.work, check=True, env=run_env(box))


@pytest.mark.parametrize(
    ("state", "wrong", "refusal"),
    [
        ("stale_key", "sed -i '/^timeout_s/d' config/settings.conf", "sets request_timeout_s 0"),
        ("stale_key", "sed -i '/timeout_s/d' config/renames.conf", "renames.conf was changed"),
        ("both_keys", "sed -i 's/^timeout_s/request_timeout_s/' config/settings.conf", "2 times"),
        (
            "local_override",
            "sed -i 's/^request_timeout_s/timeout_s/' config/settings.conf",
            "still",
        ),
        ("local_override", "git add -f config/local.conf && git commit -qm x", "still sets"),
    ],
)
def test_the_checker_refuses_the_obvious_wrong_fixes(state: str, wrong: str, refusal: str) -> None:
    box = build_sandbox(SEED_FOR[state], ["config_renamed"])
    try:
        _fix(box, wrong)
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert not verdict.ok
    assert refusal in verdict.detail, verdict.detail


def test_committing_the_migrated_override_is_refused() -> None:
    box = build_sandbox(SEED_FOR["local_override"], ["config_renamed"])
    try:
        replay(_gold("migrate_local"), box)
        assert SPEC.check(box).ok
        _fix(box, f"git add -f {LOCAL_FILE} && git commit -qm 'publish my override'")
        verdict = SPEC.check(box)
    finally:
        box.destroy()
    assert not verdict.ok and "tracked" in verdict.detail


def test_a_state_without_a_config_tree_renders_as_it_did(make_sandbox) -> None:
    """The fields are left out when empty, so no git state's arm-2 text moves (ADR-0041)."""
    observed = StateFingerprint.observe(make_sandbox(0, ["diverged"]))
    assert "config_" not in observed.as_text()
    box = build_sandbox(SEED_FOR["both_keys"], ["config_renamed"])
    try:
        text = StateFingerprint.observe(box).as_text()
    finally:
        box.destroy()
    assert "config_stale_keys: config/settings.conf: timeout_s -> request_timeout_s" in text
    assert "config_ignored_files" not in text, "an empty config field is still left out"


def test_the_rename_table_lists_every_pair_and_the_settings_use_new_names_elsewhere() -> None:
    box = build_sandbox(SEED_FOR["stale_key"], ["config_renamed"])
    try:
        settings = (box.work / SETTINGS_FILE).read_text(encoding="utf-8")
    finally:
        box.destroy()
    keys = {key for key, _ in config_assignments(settings)}
    for old, new in RENAMES:
        if old == "timeout_s":
            assert old in keys and new not in keys
        else:
            assert new in keys and old not in keys, "`retries` is not `max_retries`"


def test_no_phrasing_names_a_resolution() -> None:
    texts = [*INTENT.phrasings, *(p for ps in INTENT.variant_phrasings.values() for p in ps)]
    for text in texts:
        for variant in VARIANTS:
            assert not re.search(rf"\b{variant}\b", text, re.IGNORECASE), (variant, text)


def test_few_requests_name_the_fault() -> None:
    assert INTENT.naming_fraction(range(200)) <= 0.35
