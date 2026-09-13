"""The control that measures how far the request text alone gets a dispatcher.

A control that has never been seen to fire is not a control, and an assertion that
cannot fail is indistinguishable from one that passes. So this file has four parts:
a positive control proving the detector fires on informed wording that fully
determines the resolution, the real assertion that the registered intents'
*uninformed* wording does not leak it, a reported -- not gated -- measurement of the
informed boundary, and a structural pin that stops an undeclared state-to-wording
channel from silently restoring the original flaw.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.textcontrol import (
    LEAKAGE_CEILING,
    TextOnlyClassifier,
    leakage_verdict,
    roc_auc,
)
from precondition_library.tasks.intent import IntentSpec, ResolutionVariant
from precondition_library.tasks.registry import ambiguous_intents

TRAIN_SEEDS = list(range(0, 40))
EVAL_SEEDS = list(range(100, 140))


def test_auc_is_one_for_a_perfect_ranking() -> None:
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0


def test_auc_is_zero_for_a_perfectly_inverted_ranking() -> None:
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0


def test_auc_is_one_half_for_all_ties() -> None:
    assert roc_auc([0.5, 0.5, 0.5, 0.5], [True, True, False, False]) == 0.5


def test_auc_rejects_a_single_class() -> None:
    with pytest.raises(ValueError, match="only one class"):
        roc_auc([0.1, 0.2], [True, True])


def test_classifier_learns_a_separable_problem() -> None:
    """The classifier must be capable of learning a separation at all, or the
    real assertion below could pass merely because the model is broken.

    Asserted as a ranking rather than an exact label flip: gradient descent on a
    separable problem reaches a correct ranking well before every point crosses
    its decision boundary, and the control only ever consumes the score. This
    ranking threshold (>= 0.99) is a capability floor for the model, distinct from
    `LEAKAGE_CEILING`, which gates a property of the *data*.
    """
    texts = ["alpha alpha alpha", "alpha alpha", "beta beta beta", "beta beta"]
    labels = ["alpha", "alpha", "beta", "beta"]
    model = TextOnlyClassifier.fit(texts, labels, epochs=600)
    scores = [model.predict_proba(text)["alpha"] for text in texts]
    assert roc_auc(scores, [True, True, False, False]) >= 0.99


def test_classifier_rejects_one_class() -> None:
    with pytest.raises(ValueError, match="at least two classes"):
        TextOnlyClassifier.fit(["a b", "c d"], ["same", "same"])


def test_regime_filter_rejects_an_empty_regime() -> None:
    """A filter that matches nothing must raise, not hand back a verdict that a
    reader would take for a clean measurement."""
    with pytest.raises(ValueError, match="no uninformed pairs"):
        leakage_verdict([], train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, informed=False)


@pytest.fixture
def determining_intent() -> IntentSpec:
    """Two resolutions, each correct for exactly one of two states.

    Each resolution has a single informed phrasing, so informed wording fully
    determines the answer -- the fixture is the positive control that proves the
    detector fires on exactly the flaw the real assertion must not find in the
    registered intents.
    """
    return IntentSpec(
        name="determining_fixture",
        fault="diverged",
        phrasings=["do the thing"],
        naming_markers=[],
        variants=[
            ResolutionVariant(
                id="clean",
                decided_by=lambda state: not state.dirty_worktree,
                rationale="fixture",
            ),
            ResolutionVariant(
                id="dirty",
                decided_by=lambda state: state.dirty_worktree,
                rationale="fixture",
            ),
        ],
        variant_phrasings={
            "clean": ["my working tree is clean"],
            "dirty": ["my working tree has uncommitted changes"],
        },
    )


def test_positive_control_the_detector_fires_on_a_determining_intent(
    determining_intent, make_state
) -> None:
    """If this test ever passes as a no-op, the real assertion is worthless.

    Asserted on the informed channel explicitly: the fixture declares one phrasing
    per resolution there, so the text fully determines the answer and the control
    must fire.
    """
    states = [make_state(dirty_worktree=False), make_state(dirty_worktree=True)]
    pairs = labelled_pairs(determining_intent, states, TRAIN_SEEDS + EVAL_SEEDS)
    verdict = leakage_verdict(pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, informed=True)
    assert verdict.auc > LEAKAGE_CEILING
    assert verdict.leaks is True


def test_uninformed_wording_does_not_leak_the_resolution(state_grid) -> None:
    """The real assertion, on the regime the primary claim is measured in.

    The shared phrasing distribution is sampled with no state, so the text cannot
    carry the resolution. This is the regression tripwire: it fails if that
    distribution ever starts leaking the answer -- the original flaw returning.
    """
    for intent in ambiguous_intents():
        pairs = labelled_pairs(
            intent, list(state_grid[intent.name].values()), TRAIN_SEEDS + EVAL_SEEDS
        )
        verdict = leakage_verdict(
            pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, informed=False
        )
        assert not verdict.leaks, f"{intent.name}: {verdict.describe()}"


def test_informed_wording_is_the_boundary_condition_reported_not_gated(state_grid) -> None:
    """Report the informed regime; do not gate on it.

    Informed wording is expected to score high: it is the boundary condition, the
    regime where the wording nearly gives the resolution away and the mechanism is
    not needed at all. Gating it would punish the domain for being realistic. It
    is still measured and carried in this assertion's message, so the number
    cannot be quietly lost. Only the ordering -- informed above uninformed -- is
    required, and both AUCs appear either way.
    """
    for intent in ambiguous_intents():
        pairs = labelled_pairs(
            intent, list(state_grid[intent.name].values()), TRAIN_SEEDS + EVAL_SEEDS
        )
        uninformed = leakage_verdict(
            pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, informed=False
        )
        informed = leakage_verdict(
            pairs, train_seeds=TRAIN_SEEDS, eval_seeds=EVAL_SEEDS, informed=True
        )
        assert informed.auc > uninformed.auc, (
            f"{intent.name}: informed wording should carry more signal than the "
            f"uninformed distribution; uninformed: {uninformed.describe()}; "
            f"informed: {informed.describe()}"
        )


def test_channel_decision_is_shared_by_sampler_and_ledger(state_grid) -> None:
    """`uses_informed_wording` and the sampled text must agree.

    The ledger files a pair under a regime using `uses_informed_wording`; if the
    sampler disagreed, pairs would be recorded in the wrong regime and the split
    would be fiction. Pinned rather than trusted.
    """
    for intent in ambiguous_intents():
        for state in state_grid[intent.name].values():
            informed = intent.informed_phrasings(state)
            assert intent.uses_informed_wording(state) is (informed is not None)
            for seed in range(30):
                text = intent.task_text(seed, state)
                if informed is None:
                    assert text in intent.phrasings, (
                        f"{intent.name}: no informed wording declared for this state, "
                        f"so the text must come from the shared list: {text!r}"
                    )
                else:
                    assert text in informed, (
                        f"{intent.name}: informed wording is declared for this state, "
                        f"so the text must come from that list: {text!r}"
                    )


def test_state_influences_wording_only_through_the_declared_map(state_grid) -> None:
    """State may reach the request only through variant_phrasings.

    If the sampler ever consulted state outside that declared map, an undeclared
    channel would exist, the text could become a label again, and a dispatch
    comparison would measure nothing -- silently.
    """
    for intent in ambiguous_intents():
        for state in state_grid[intent.name].values():
            informed = intent.informed_phrasings(state)
            for seed in range(30):
                text = intent.task_text(seed, state)
                if informed:
                    assert text in informed, (
                        f"{intent.name}: text fell outside the declared informed "
                        f"list for this state: {text!r}"
                    )
                else:
                    assert text in intent.phrasings, (
                        f"{intent.name}: no informed wording declared for this state, "
                        f"so the text must come from the shared list: {text!r}"
                    )
