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
