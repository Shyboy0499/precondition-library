"""The state-reading control (#295, ADR-0047).

`bench.state_classifier` fits a decision tree per intent over generic fingerprint features and is
scored on Figure 1's pairs. These tests pin what makes its result a fair control:

* the features are generic -- every field, every pairwise overlap and equality -- with no name
  taken from an intent's rule;
* the training seeds are the build's admit seeds, disjoint from both blocks it is scored on;
* fit on built states, it recovers the rules on states it never saw;
* the committed figures are what the summary says.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("sklearn")

from precondition_library.bench import state_classifier as sc  # noqa: E402
from precondition_library.bench.admit_set import admit_seeds  # noqa: E402
from precondition_library.bench.heldout import HELD_OUT_FAULTS  # noqa: E402
from precondition_library.bench.library_pairs import _measured_intents  # noqa: E402
from precondition_library.bench.splits import EVAL_SEEDS, HELD_OUT_SEEDS  # noqa: E402
from precondition_library.signatures import StateFingerprint  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "results" / "state-classifier-2026-10-26"


def test_the_features_are_generic() -> None:
    names = set(sc.features(StateFingerprint.model_validate(_empty_state())))
    for field in StateFingerprint.model_fields:
        assert field in names or f"len({field})" in names or any(field in n for n in names), field
    rule_words = {"decided_by", "conflicting_files", "has_local_only_commits", "stash", "rebase"}
    assert not any(word in name for name in names for word in rule_words)


def _empty_state() -> dict:
    return {
        name: (
            []
            if str(field.annotation).startswith("list")
            else ""
            if field.annotation is str
            else False
            if field.annotation is bool
            else 0
        )
        for name, field in StateFingerprint.model_fields.items()
    }


def test_training_seeds_are_disjoint_from_both_scored_blocks() -> None:
    training = {seed for fault in HELD_OUT_FAULTS for seed in admit_seeds(fault)}
    assert not training & set(EVAL_SEEDS)
    assert not training & set(HELD_OUT_SEEDS)


def test_a_fit_recovers_the_rules_on_states_it_never_saw() -> None:
    """Fit on the build's states, scored on four eval seeds per fault: every fire is right."""
    intents = _measured_intents(HELD_OUT_FAULTS)
    training = sc._states(HELD_OUT_FAULTS, {f: admit_seeds(f) for f in HELD_OUT_FAULTS})
    classifier = sc.StateClassifier(intents).fit([state for _, _, state in training])
    pairs, decided = sc.outcomes(classifier, HELD_OUT_FAULTS, [2000, 2001, 2002, 2005])
    fires = [(p, o) for p, o in zip(pairs, decided, strict=True) if o.fired_variant is not None]
    assert fires, "the control fires somewhere"
    assert all(o.fire_is_right(o.fired_variant) for _, o in fires)
    assert not any(p.correct_variant is None for p, _ in fires), "no fire on a fault-free pair"


@pytest.mark.parametrize(("block", "fires", "wrong"), [("eval", 190, 0), ("held-out", 200, 0)])
def test_the_committed_figures(block: str, fires: int, wrong: int) -> None:
    report = json.loads((RESULTS / f"{block}.json").read_text(encoding="utf-8"))
    point = report["at_every_fire"]
    assert (point["coverage"]["numerator"], point["coverage"]["denominator"]) == (fires, 400)
    assert point["mismatch"]["numerator"] == wrong == len(report["wrong_fires"])
    assert report["training_states"] == 56
    assert (RESULTS / "trees.txt").is_file()


# --- the library-scoped control (ADR-0052) ----------------------------------------------------


def test_the_library_control_fires_the_most_probable_resolution_of_any_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intents = _measured_intents(HELD_OUT_FAULTS)
    classifier = sc.StateClassifier(intents)
    first, second, third = intents[0].name, intents[1].name, intents[2].name
    said = {first: (None, 0.9), second: ("take_upstream", 0.6), third: ("merge", 0.8)}
    monkeypatch.setattr(
        classifier, "decide", lambda intent, state: said.get(intent.name, (None, 1.0))
    )
    state = StateFingerprint.model_validate(_empty_state())
    assert classifier.decide_library(state) == ("merge", 0.8)

    said[second] = ("take_upstream", 0.8)  # a tie goes to the intent listed first
    assert classifier.decide_library(state) == ("take_upstream", 0.8)

    said.clear()
    assert classifier.decide_library(state) == (None, 0.0), "every tree predicts none"


def test_fit_on_the_build_the_library_control_fires_what_the_states_own_intent_accepts() -> None:
    """On unseen eval states, whatever intent it borrows from, its fire is one the rule of the
    injected fault's own intent accepts, and it fires nothing on a fault-free state."""
    from precondition_library.tasks.faults import build_sandbox

    intents = _measured_intents(HELD_OUT_FAULTS)
    by_fault = {intent.fault: intent for intent in intents}
    training = sc._states(HELD_OUT_FAULTS, {f: admit_seeds(f) for f in HELD_OUT_FAULTS})
    classifier = sc.StateClassifier(intents).fit([state for _, _, state in training])
    fired = 0
    for seed in (2000, 2001):
        for fault in (None, *HELD_OUT_FAULTS):
            box = build_sandbox(seed, [] if fault is None else [fault])
            try:
                state = StateFingerprint.observe(box)
            finally:
                box.destroy()
            variant, _ = classifier.decide_library(state)
            if fault is None:
                assert variant is None, f"seed {seed}: fired {variant} on a fault-free state"
                continue
            accepted = set(by_fault[fault].acceptable_variants(state))
            assert variant in accepted, (seed, fault, variant, accepted)
            fired += 1
    assert fired == 2 * len(HELD_OUT_FAULTS)


def test_control_r_declines_the_refusal_states_it_was_given() -> None:
    """Study 2's Control-R (refusal-population §6), on real conflicts nothing can express: ten of
    stage B's recorded states, which the plain fit fires on, are declined once given as refusals,
    and every training state keeps its rule's label."""
    from precondition_library.bench.library_control import _read

    stage = Path(__file__).resolve().parents[1] / "results/real-merges-2026-10-26/stage-B"
    manifest, labels, _, observed = _read(stage)
    kinds = {case.index: case.kind for case in manifest.cases}
    inexpressible = {
        lab.index for lab in labels if kinds[lab.index] == "positive" and not lab.acceptable
    }
    refusals = [o.state for o in observed if o.index in inexpressible][:10]
    assert len(refusals) == 10

    intents = _measured_intents(HELD_OUT_FAULTS)
    training = sc._states(HELD_OUT_FAULTS, {f: admit_seeds(f) for f in HELD_OUT_FAULTS})
    states = [state for _, _, state in training]
    trained = [sc.features(state) for state in states]
    assert not any(sc.features(r) in trained for r in refusals), (
        "no refusal repeats a training state"
    )
    plain = sc.StateClassifier(intents).fit(states)
    assert all(plain.decide_library(state)[0] is not None for state in refusals)

    control_r = sc.StateClassifier(intents).fit(states, refusals=refusals)
    for state in refusals:
        assert control_r.decide_library(state) == (None, 0.0)
    for state in states:
        for intent in intents:
            variant = intent.correct_variant(state)
            expected = variant.id if variant is not None else None
            assert control_r.decide(intent, state)[0] == expected, "the training rules still hold"
