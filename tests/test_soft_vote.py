"""Arm 2b: a soft vote over arm 3's own probe features (issue #7, ADR-0016).

A program's score is the fraction of its preconditions that hold; arm 3 is the vote
at threshold 1.0. These tests pin:

* the score, and that the vote at 1.0 makes exactly arm 3's choices on real sandboxes;
* the threshold rule -- most correct decisions on the tune outcomes, ties to the
  stricter floor, abstaining-everywhere always a candidate;
* the Claim 2 verdict -- restated only on a genuine tie, never when the matched soft
  point *is* the hard rule (a tautological tie, which is what gold produces); and
* the arm end to end, including the refusal to run without a learned threshold.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeProvider, gold_programs, store_programs

from precondition_library.agents.dispatch import dispatch_soft_vote
from precondition_library.bench.coverage import OperatingPoint, PairOutcome
from precondition_library.bench.ledger import Arm, OccurrenceRole
from precondition_library.bench.report import Rate
from precondition_library.bench.run import run_benchmark, run_episode
from precondition_library.bench.soft_vote import (
    CLAIM2_AS_REGISTERED,
    CLAIM2_RESTATED,
    NEVER_FIRES,
    claim2_verdict,
    learn_soft_threshold,
    soft_vote_outcomes,
)
from precondition_library.library import Library, soft_vote_score
from precondition_library.program import (
    EpisodeOutcome,
    GroundTruthResult,
    PredicateResult,
    ProgramStatus,
)
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox

INTENTS = ("sync_fork_with_upstream", "restore_submodule_state")


def _gold_library(path: Path, *, soft_threshold: float | None = None) -> Library:
    programs = [
        program.model_copy(update={"status": ProgramStatus.ADMITTED})
        for intent in INTENTS
        for program in gold_programs(intent)
    ]
    library = store_programs(path, programs)
    library.soft_threshold = soft_threshold
    return library


def _result(*held: bool, refused: tuple[bool, ...] = ()) -> GroundTruthResult:
    refused = refused or tuple(False for _ in held)
    return GroundTruthResult(
        ok=all(held),
        predicates=[
            PredicateResult(name=f"p{i}", ok=ok, refused=r)
            for i, (ok, r) in enumerate(zip(held, refused, strict=True))
        ],
    )


def _outcome(correct: str | None, fired: str | None, score: float | None) -> PairOutcome:
    return PairOutcome(correct_variant=correct, fired_variant=fired, score=score, informed=False)


def _point(threshold: float | None, fired: int, total: int, wrong: int) -> OperatingPoint:
    return OperatingPoint(
        threshold=threshold,
        coverage=Rate(numerator=fired, denominator=total),
        mismatch=Rate(numerator=wrong, denominator=fired),
        mismatch_interval=None,
    )


# --- the score ------------------------------------------------------------------


def test_the_score_is_the_share_of_preconditions_that_hold() -> None:
    assert soft_vote_score(_result(True, True, False)) == pytest.approx(2 / 3)
    assert soft_vote_score(_result(True, True)) == 1.0
    assert soft_vote_score(_result(False, False)) == 0.0


def test_an_empty_precondition_set_scores_one_as_arm_3_accepts_it() -> None:
    assert soft_vote_score(GroundTruthResult(ok=True, predicates=[])) == 1.0


def test_a_refused_probe_counts_as_not_holding() -> None:
    assert soft_vote_score(_result(True, False, refused=(False, True))) == 0.5


@pytest.mark.parametrize("fault,seed", [("diverged", 0), ("diverged", 1), ("submodule_moved", 0)])
def test_the_vote_at_one_makes_exactly_arm_3s_choices(
    tmp_path: Path, fault: str, seed: int
) -> None:
    """Arm 3 is the soft vote at threshold 1.0: same programs, in the same order."""
    library = _gold_library(tmp_path / "lib", soft_threshold=1.0)
    box = build_sandbox(seed, [fault])
    try:
        soft = [item.program.id for item in library.match_soft(box)]
        hard = [program.id for program in library.match_preconditions(box)]
    finally:
        box.destroy()
    assert soft == hard and soft, "gold resolves every state, so arm 3 fires something"


def test_the_matcher_refuses_to_run_without_a_learned_threshold(tmp_path: Path) -> None:
    library = _gold_library(tmp_path / "lib")
    box = build_sandbox(1, ["diverged"])
    try:
        with pytest.raises(ValueError, match="learned soft_threshold"):
            library.match_soft(box)
    finally:
        box.destroy()


def test_dispatch_records_the_score(tmp_path: Path) -> None:
    library = _gold_library(tmp_path / "lib", soft_threshold=0.5)
    box = build_sandbox(1, ["diverged"])  # empty_local_commits -> discard
    try:
        signature = TaskSignature(
            intent="unused", fingerprint=StateFingerprint.observe(box), target=str(box.work)
        )
        decision = dispatch_soft_vote(signature, library, box)
    finally:
        box.destroy()
    assert decision.program is not None and decision.program.variant == "discard"
    assert decision.score == 1.0


# --- the threshold rule ---------------------------------------------------------


def test_the_threshold_maximises_correct_decisions() -> None:
    outcomes = [
        _outcome("merge", "merge", 1.0),
        _outcome("rebase", "rebase", 0.75),
        _outcome(None, "merge", 0.5),  # a negative: firing here is wrong
    ]
    # 0.75 fires the two right ones and abstains on the negative: 3 of 3.
    assert learn_soft_threshold(outcomes) == 0.75


def test_ties_go_to_the_stricter_threshold() -> None:
    outcomes = [
        _outcome("merge", "merge", 1.0),
        _outcome("rebase", "merge", 0.5),  # wrong whether fired or abstained
    ]
    # 1.0 and 0.5 both make one correct decision; 1.0 is stricter.
    assert learn_soft_threshold(outcomes) == 1.0


def test_abstaining_everywhere_is_learned_when_it_is_most_accurate() -> None:
    outcomes = [_outcome(None, "merge", 1.0), _outcome(None, "rebase", 0.5)]
    assert learn_soft_threshold(outcomes) == NEVER_FIRES
    assert NEVER_FIRES > 1.0


def test_learning_refuses_an_empty_tune_set() -> None:
    with pytest.raises(ValueError, match="no outcomes"):
        learn_soft_threshold([])


# --- the Claim 2 verdict -----------------------------------------------------------


def test_a_genuine_tie_restates_claim_2() -> None:
    """A soft point below 1.0 with the same mismatch as arm 3, on enough fires to show it."""
    arm3 = _point(None, 400, 800, 0)
    soft_curve = [_point(0.5, 400, 800, 0)]
    verdict = claim2_verdict(soft_curve, arm3)
    assert verdict.collapsed is False
    assert verdict.restate is True
    assert verdict.claim == CLAIM2_RESTATED
    assert "mismatch" in verdict.reason


def test_a_tie_with_the_hard_rule_itself_is_collapsed_not_restated() -> None:
    """At threshold 1.0 the vote *is* arm 3, so equivalence says nothing about softness."""
    arm3 = _point(None, 400, 800, 0)
    soft_curve = [_point(1.0, 400, 800, 0), _point(0.5, 800, 800, 400)]
    verdict = claim2_verdict(soft_curve, arm3)
    assert verdict.collapsed is True
    assert verdict.restate is False
    assert verdict.claim == CLAIM2_AS_REGISTERED


def test_a_soft_vote_that_misfires_more_keeps_the_registered_claim() -> None:
    arm3 = _point(None, 400, 800, 0)
    soft_curve = [_point(0.5, 400, 800, 120)]
    verdict = claim2_verdict(soft_curve, arm3)
    assert verdict.restate is False and verdict.collapsed is False
    assert verdict.claim == CLAIM2_AS_REGISTERED


# --- collection and the arm end to end ---------------------------------------------------


def test_outcomes_pair_each_faulted_state_with_a_clean_negative(tmp_path: Path) -> None:
    library = _gold_library(tmp_path / "lib")
    outcomes = soft_vote_outcomes(library, ["diverged"], [1])
    assert [outcome.correct_variant for outcome in outcomes] == ["discard", None]
    positive = outcomes[0]
    assert positive.fired_variant == "discard" and positive.score == 1.0
    assert all(outcome.informed is False for outcome in outcomes)


def test_run_benchmark_refuses_a_soft_vote_arm_without_a_threshold(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="learned soft_threshold"):
        run_benchmark(
            arms=[Arm.SOFT_VOTE],
            faults=["diverged"],
            occurrences=1,
            seeds=[1],
            out=tmp_path / "ledger.jsonl",
            model="fake",
            provider=FakeProvider(),
        )


def test_a_soft_vote_hit_replays_for_zero_tokens_and_records_its_threshold(
    tmp_path: Path,
) -> None:
    library = _gold_library(tmp_path / "lib", soft_threshold=1.0)
    provider = FakeProvider(raises=AssertionError("a soft-vote hit must not call the model"))

    record = run_episode(
        Arm.SOFT_VOTE,
        "diverged",
        1,  # empty_local_commits -> discard
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=library,
        model="fake",
    )

    assert provider.calls == []
    assert record.arm is Arm.SOFT_VOTE
    assert record.outcome is EpisodeOutcome.SUCCESS
    assert record.fired_variant == "discard" == record.correct_variant
    assert record.dispatch_score == 1.0
    assert record.soft_threshold == 1.0
    assert record.admission_gate == "two_sided"
