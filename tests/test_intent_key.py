"""Arm 2c: dispatch by the request string, abstaining on a conflicting key (issue #7).

The lookup-table baseline normalises the request and fires the program compiled
from a request with the same key (ADR-0015). These tests pin:

* the key -- case and punctuation fold away, slot values become placeholders, and
  every shipped phrasing keeps a key of its own;
* the abstain rule -- a key whose admitted programs implement two variants fires
  nothing, and only `admitted` programs count;
* the arm end to end -- a key hit replays with no model call, and an abstaining key
  falls back to the agent like any other miss; and
* the pair-level outcome uses the same rule the episodes do.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from conftest import FakeProvider, gold_program, store_programs

from precondition_library.agents.dispatch import dispatch_intent_key
from precondition_library.bench.coverage import intent_key_outcomes
from precondition_library.bench.ledger import Arm, OccurrenceRole
from precondition_library.bench.pairs import label
from precondition_library.bench.run import _dispatch, run_episode
from precondition_library.intent_key import agreeing, intent_key
from precondition_library.program import EpisodeOutcome, Program, ProgramStatus
from precondition_library.provider import Completion, TokenUsage
from precondition_library.signatures import TaskSignature
from precondition_library.tasks.faults.diverged import INTENT as SYNC_INTENT
from precondition_library.tasks.faults.diverged import SPEC as DIVERGED
from precondition_library.tasks.faults.submodule_moved import INTENT as SUBMODULE_INTENT
from precondition_library.tasks.state_grid import STATE_GRID

DISCARD_SEED = 1  # diverged: empty_local_commits -> discard
_CALL_IDS = itertools.count(1)


def _keyed(variant: str, request: str, *, status=ProgramStatus.ADMITTED, suffix="") -> Program:
    """A gold resolution re-stored as if compiled from `request`."""
    program = gold_program(variant)
    return program.model_copy(
        update={
            "id": f"{program.id}{suffix}",
            "status": status,
            "provenance": program.provenance.model_copy(update={"compiled_from_task": request}),
        }
    )


def _signature(request: str) -> TaskSignature:
    state = STATE_GRID["sync_fork_with_upstream"]["empty_local_commits"]
    return TaskSignature(intent=request, fingerprint=state, target="/nowhere")


# --- the key -----------------------------------------------------------------


def test_case_and_punctuation_fold_away() -> None:
    assert intent_key("Reconcile this branch with upstream.") == intent_key(
        "reconcile   this branch, with upstream"
    )


def test_slot_values_become_placeholders() -> None:
    assert intent_key("Sync `main` with upstream") == intent_key("sync `dev` with upstream")
    assert intent_key("fix vendor/lib now") == intent_key("fix third_party/dep now")
    assert intent_key("revert 3f9c2ab1 please") == intent_key("revert a1b2c3d please")
    assert intent_key("keep 3 commits") == intent_key("keep 12 commits")


def test_an_all_letter_hex_word_is_not_a_commit_id() -> None:
    assert "defaced" in intent_key("the branch looks defaced")


@pytest.mark.parametrize("intent", [SYNC_INTENT, SUBMODULE_INTENT], ids=lambda i: i.name)
def test_every_shipped_phrasing_keeps_its_own_key(intent) -> None:
    """Normalisation must not merge two phrasings, or the table is coarser than the text."""
    keys = [intent_key(text) for text in intent.phrasings]
    assert len(set(keys)) == len(keys)


# --- the abstain rule --------------------------------------------------------

_REQUEST = SYNC_INTENT.phrasings[0]


def test_one_variant_under_the_key_fires() -> None:
    keyed = agreeing(
        [_keyed("discard", _REQUEST), _keyed("discard", _REQUEST, suffix="-b")], _REQUEST
    )
    assert [program.variant for program in keyed] == ["discard", "discard"]
    assert [program.id for program in keyed] == sorted(program.id for program in keyed)


def test_two_variants_under_the_key_abstain() -> None:
    assert agreeing([_keyed("discard", _REQUEST), _keyed("merge", _REQUEST)], _REQUEST) == []


def test_only_admitted_programs_count() -> None:
    """A demoted merge under the key does not make the admitted discard abstain."""
    programs = [
        _keyed("discard", _REQUEST),
        _keyed("merge", _REQUEST, status=ProgramStatus.DEMOTED),
        _keyed("rebase", _REQUEST, status=ProgramStatus.CANDIDATE),
    ]
    assert [program.variant for program in agreeing(programs, _REQUEST)] == ["discard"]


def test_a_different_key_does_not_match() -> None:
    assert agreeing([_keyed("discard", _REQUEST)], SYNC_INTENT.phrasings[1]) == []


def test_hand_written_gold_matches_no_request() -> None:
    """Gold's provenance names no request, so a key lookup over it never fires."""
    gold = [
        gold_program(v).model_copy(update={"status": ProgramStatus.ADMITTED})
        for v in ("discard", "rebase", "merge")
    ]
    assert all(agreeing(gold, text) == [] for text in SYNC_INTENT.phrasings)


def test_the_library_matcher_and_dispatch_use_the_rule(tmp_path: Path) -> None:
    library = store_programs(tmp_path / "lib", [_keyed("discard", _REQUEST)])
    decision = dispatch_intent_key(_signature(_REQUEST), library)
    assert decision.program is not None and decision.program.variant == "discard"
    assert decision.score is None

    conflicted = store_programs(
        tmp_path / "lib2", [_keyed("discard", _REQUEST), _keyed("merge", _REQUEST)]
    )
    assert dispatch_intent_key(_signature(_REQUEST), conflicted).program is None


def test_a_non_dispatching_arm_is_refused_by_the_dispatch_table(tmp_path: Path) -> None:
    library = store_programs(tmp_path / "lib", [])
    with pytest.raises(ValueError, match="does not dispatch"):
        _dispatch(Arm.REACT, _signature(_REQUEST), library, box=None)  # type: ignore[arg-type]


# --- the arm, end to end ------------------------------------------------------


def _tool(command: str) -> Completion:
    call = {
        "id": f"call_{next(_CALL_IDS)}",
        "type": "function",
        "function": {"name": "run_git", "arguments": json.dumps({"command": command})},
    }
    return Completion(
        tool_calls=[call],
        usage=TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10),
        model="fake",
    )


def _finish() -> Completion:
    return Completion(
        text="done",
        usage=TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10),
        model="fake",
    )


def test_a_key_hit_replays_for_zero_tokens(tmp_path: Path) -> None:
    request = DIVERGED.task_text(DISCARD_SEED)
    library = store_programs(tmp_path / "lib", [_keyed("discard", request)])
    provider = FakeProvider(raises=AssertionError("a key hit must not call the model"))

    record = run_episode(
        Arm.INTENT_KEY,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=library,
        model="fake",
    )

    assert provider.calls == []
    assert record.arm is Arm.INTENT_KEY
    assert record.outcome is EpisodeOutcome.SUCCESS
    assert record.fired_variant == "discard" == record.correct_variant
    assert record.llm_calls == 0
    assert record.dispatch_score is None
    assert record.admission_gate == "two_sided", "2c dispatches from a gated library"


def test_an_abstaining_key_falls_back_to_the_agent(tmp_path: Path) -> None:
    request = DIVERGED.task_text(DISCARD_SEED)
    library = store_programs(
        tmp_path / "lib", [_keyed("discard", request), _keyed("merge", request)]
    )
    provider = FakeProvider(
        _tool("git fetch -q upstream"), _tool("git reset --hard upstream/main"), _finish()
    )

    record = run_episode(
        Arm.INTENT_KEY,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=library,
        model="fake",
        frozen=True,  # no compile on fallback, so the scripted solve is the whole spend
    )

    assert record.fired_variant is None, "the conflicting key fired nothing"
    assert record.outcome is EpisodeOutcome.FALLBACK
    assert record.succeeded is True
    assert record.llm_calls == 3


# --- the pair-level outcome ----------------------------------------------------


def test_pair_outcomes_apply_the_same_rule() -> None:
    state = STATE_GRID["sync_fork_with_upstream"]["empty_local_commits"]
    pair = label(SYNC_INTENT, DISCARD_SEED, state, uninformed=True)
    fires = intent_key_outcomes([pair], [_keyed("discard", pair.task_text)])
    abstains = intent_key_outcomes(
        [pair], [_keyed("discard", pair.task_text), _keyed("merge", pair.task_text)]
    )
    assert fires[0].fired_variant == "discard" and fires[0].score is None
    assert abstains[0].fired_variant is None
    assert fires[0].correct_variant == "discard"
