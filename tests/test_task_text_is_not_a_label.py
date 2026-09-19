"""The control that measures how far the request text alone gets a dispatcher.

A control that has never been seen to fire is not a control, and an assertion that
cannot fail is indistinguishable from one that passes. So this file has four parts:
a positive control proving the detector fires on informed wording that fully
determines the resolution, a reported -- not gated -- measurement of the informed
boundary, a plumbing tripwire that fails if the uninformed sampler starts
consulting state (its AUC of 0.500 is an identity of the construction, not
evidence about the phrasing distribution), and a structural pin -- including an
equivalence-class test -- that stops an undeclared state-to-wording channel from
silently restoring the original flaw.

A fifth part is added here because it is the same channel seen from the other side:
the *environment*. Everything above guards the task text; that control guards the clone.
Issue #103 found the injected state written in plaintext under `refs/sandbox/`, where a
precondition could read the resolution rather than diagnose it. It was pinned as a strict
`xfail` so it could not be forgotten, and fixing the leak turned it into the assertion
below -- which is why the marker is gone rather than lingering.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from precondition_library.bench.pairs import labelled_pairs
from precondition_library.bench.textcontrol import (
    LEAKAGE_CEILING,
    TextOnlyClassifier,
    leakage_verdict,
    roc_auc,
)
from precondition_library.runtime.probes import SHELL
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
    `LEAKAGE_CEILING`, which trips if the uninformed sampler starts consulting
    state.
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


def test_overlapping_train_and_eval_seeds_are_rejected(determining_intent, make_state) -> None:
    """A split that shares seeds would evaluate on instances seen in training."""
    states = [make_state(dirty_worktree=False), make_state(dirty_worktree=True)]
    pairs = labelled_pairs(determining_intent, states, [0, 1, 2])
    with pytest.raises(ValueError, match="disjoint or the evaluation is contaminated"):
        leakage_verdict(pairs, train_seeds=[0, 1], eval_seeds=[1, 2], informed=True)


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


def test_uninformed_sampler_never_consults_state(state_grid) -> None:
    """A plumbing tripwire on the regime the primary claim is measured in.

    On uninformed requests the sampler never consults state, so every state
    receives the same text for a given seed, every positive has a negative with an
    identical score, and the AUC is 0.500 for any classifier and any phrasing
    list -- including a deliberately leaky one. That is an identity of the
    construction, not a measurement, so this test can fail for exactly one
    reason: the sampler starting to consult state, the regression that would
    restore the original flaw. It is not evidence about the phrasing
    distribution and cannot certify one.
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


def test_same_declared_phrasings_imply_same_text_for_every_seed(make_state) -> None:
    """Two states that declare the same phrasing list must sample identical text.

    The membership assertions above cannot see two undeclared channels: a phrase
    keyed on a fingerprint field that happens to be constant across the fixture
    grid (for example `upstream_ahead`), and state used to choose the *index*
    inside the declared informed list. Both keep every sampled text inside the
    declared list, so both pass membership. This test closes them by pairing
    states that differ on every fingerprint field the grid holds constant while
    resolving to the same declared list, then requiring seed-for-seed identity
    over a wide seed range. The pairs are constructed because the grid holds one
    state per resolution and therefore contains no such pair.
    """
    pairs = {
        "sync_fork_with_upstream": (
            make_state(
                dirty_worktree=True,
                branch="feature",
                upstream_ahead=7,
                upstream_behind=3,
                has_locked_branch=True,
                has_submodule_reference=True,
                submodule_initialised=True,
                submodule_pin_matches_upstream=False,
                upstream_still_references_submodule=False,
                local_touched_files=["docs/a.md", "docs/b.md"],
                upstream_touched_files=["src/app.py"],
                remotes=["origin", "upstream", "fork"],
            ),
            make_state(
                dirty_worktree=False,
                branch="main",
                upstream_ahead=1,
                upstream_behind=5,
                has_locked_branch=False,
                has_submodule_reference=False,
                submodule_initialised=False,
                submodule_pin_matches_upstream=True,
                upstream_still_references_submodule=True,
                local_touched_files=["notes.txt"],
                upstream_touched_files=["src/other.py", "src/app.py"],
                remotes=["origin"],
            ),
        ),
        "restore_submodule_state": (
            make_state(
                dirty_worktree=True,
                branch="feature",
                upstream_ahead=7,
                upstream_behind=3,
                has_locked_branch=True,
                has_submodule_reference=True,
                submodule_initialised=True,
                submodule_pin_matches_upstream=False,
                local_touched_files=["docs/a.md"],
                upstream_touched_files=["src/app.py"],
                remotes=["origin", "upstream", "fork"],
            ),
            make_state(
                dirty_worktree=False,
                branch="main",
                upstream_ahead=1,
                upstream_behind=5,
                has_locked_branch=False,
                has_submodule_reference=False,
                submodule_initialised=True,
                submodule_pin_matches_upstream=False,
                local_touched_files=["notes.txt"],
                upstream_touched_files=["src/other.py"],
                remotes=["origin"],
            ),
        ),
    }
    for intent in ambiguous_intents():
        left, right = pairs[intent.name]
        left_list = intent.informed_phrasings(left)
        assert left != right, f"{intent.name}: the paired states must differ on fingerprint fields"
        assert left_list is not None, f"{intent.name}: the pair must exercise informed wording"
        assert left_list == intent.informed_phrasings(right), (
            f"{intent.name}: the pair must share one declared informed list"
        )
        for seed in range(200):
            left_text = intent.task_text(seed, left)
            right_text = intent.task_text(seed, right)
            assert left_text == right_text, (
                f"{intent.name}: state reached the wording outside the declared map; "
                f"seed {seed} sampled {left_text!r} for one state and "
                f"{right_text!r} for the other"
            )


def test_no_phrasing_names_a_resolution(state_grid) -> None:
    """The check the AUC cannot make: a phrasing must not state the answer.

    Neither regime is gated on the words themselves. The uninformed AUC is fixed at
    0.500 by state-independent sampling whatever the phrasings say, and the informed
    regime is reported rather than gated -- so a shared phrasing reading "use
    rebase" would hand the resolution to a text-only dispatcher while every other
    gate stayed green. Matching variant ids as whole words catches the literal case;
    it cannot catch a paraphrase that reveals the answer without naming it, which is
    what the reported informed AUC measures.
    """
    for intent in ambiguous_intents():
        ids = [variant.id for variant in intent.variants]
        lists = {"shared": intent.phrasings, **intent.variant_phrasings}
        for name, texts in lists.items():
            for text in texts:
                named = sorted(i for i in ids if re.search(rf"\b{re.escape(i)}\b", text, re.I))
                assert not named, f"{intent.name} [{name}] names {named}: {text!r}"


# --- the environment half of the same channel (issue #103) --------------------


@pytest.mark.parametrize("seed", [0, 1, 4])
def test_the_environment_does_not_hand_a_probe_the_resolution(seed, make_sandbox) -> None:
    """The control above guards the request text. This is the environment.

    `inject` used to call `store_blob(work, "refs/sandbox/submodule-state", state)`, so
    the resolution label -- `init`, `repin` or `remove` -- sat in the clone the agent
    works in, and `runtime/probes.py` runs probes with `cwd=env.work`. A precondition
    could therefore be exactly this probe, and admission could not reject it: the negative
    classes check states a program must *not* fire in, and this one fires in precisely the
    state it is supposed to.

    All three states are checked, because a fix that removed the label for one of them
    would leave the others readable. Written as a probe rather than as a file read because
    that is the path that matters: what a compiled program may do is what a probe may do.
    """
    box = make_sandbox(seed, ["submodule_moved"])

    probe = subprocess.run(
        [*SHELL, "git cat-file -p refs/sandbox/submodule-state"],
        cwd=box.work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert probe.returncode != 0, (
        f"a probe read the injected state from the environment: {probe.stdout.strip()!r}. "
        f"The framework should not be able to hand a precondition its answer (issue #103)."
    )
