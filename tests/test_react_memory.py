"""Arm 1b: ReAct with a memory of its own past successes (issue #7, ADR-0017).

1b is arm 1 plus the most similar trajectories it has declared finished, placed in
the user message. These tests pin the four properties that keep it a fair baseline:

* what is stored is the commands that ran, and only from episodes the *model*
  declared done -- a wrong-but-declared episode is remembered and a failed one is
  not, so no ground truth reaches the memory;
* recall is deterministic -- most similar first, recent wins a tie, unrelated
  entries never paid for;
* the system prompt every arm sends is unchanged, and arm 1 is untouched; and
* end to end, 1b runs the same plan as arm 1 and its second episode sees its first.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from conftest import FakeProvider, gold_programs, store_programs

from precondition_library.agents.memory import (
    MAX_COMMANDS,
    SuccessMemory,
    render,
    successful_commands,
)
from precondition_library.agents.react import SYSTEM_PROMPT, solve
from precondition_library.bench.ledger import Arm, OccurrenceRole, read
from precondition_library.bench.run import run_benchmark, run_episode
from precondition_library.library import Library
from precondition_library.program import EpisodeOutcome, ProgramStatus
from precondition_library.provider import Completion, TokenUsage
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox

_CALL_IDS = itertools.count(1)

# diverged seeds 0 and 1013 both inject `overlapping_files` (merge), the same instance.
VARIANT_SEED, REPLAY_SEED = 0, 1013


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


def _merge_solve() -> list[Completion]:
    return [_tool("git fetch -q upstream"), _tool("git merge --no-edit upstream/main"), _finish()]


def _tool_entry(command: str, ok: bool) -> dict:
    return {"role": "tool", "command": command, "content": "", "ok": ok}


# --- what is stored, and recalled ------------------------------------------------


def test_only_commands_that_ran_are_kept_in_order() -> None:
    transcript = [
        {"role": "user", "content": "task"},
        _tool_entry("git fetch upstream", True),
        _tool_entry("git rebase nonsense", False),
        _tool_entry("git merge --no-edit upstream/main", True),
    ]
    assert successful_commands(transcript) == (
        "git fetch upstream",
        "git merge --no-edit upstream/main",
    )


def test_an_entry_keeps_at_most_max_commands() -> None:
    transcript = [_tool_entry(f"git status --n{i}", True) for i in range(MAX_COMMANDS + 5)]
    assert len(successful_commands(transcript)) == MAX_COMMANDS


def test_a_solve_with_no_successful_command_is_not_stored() -> None:
    memory = SuccessMemory()
    memory.record("sync the fork", [_tool_entry("git bogus", False)])
    assert len(memory) == 0


def test_recall_is_most_similar_first_and_skips_unrelated_entries() -> None:
    memory = SuccessMemory()
    memory.record("sync my fork with upstream now", [_tool_entry("git merge x", True)])
    memory.record("rename release branch", [_tool_entry("git branch -m a b", True)])
    memory.record("sync this fork with upstream", [_tool_entry("git fetch upstream", True)])
    # Against the query, the third entry shares 4 of 7 tokens and the first 4 of 8;
    # the second shares none, so it is never recalled (and never paid for).
    recalled = memory.recall("please sync the fork with upstream")
    assert [entry.request for entry in recalled] == [
        "sync this fork with upstream",
        "sync my fork with upstream now",
    ]


def test_a_tie_goes_to_the_more_recent_entry() -> None:
    memory = SuccessMemory()
    memory.record("sync the fork", [_tool_entry("git fetch first", True)])
    memory.record("sync the fork", [_tool_entry("git fetch second", True)])
    assert memory.recall("sync the fork", k=1)[0].commands == ("git fetch second",)


def test_render_states_the_entries_and_warns_they_may_not_apply() -> None:
    memory = SuccessMemory()
    memory.record("sync the fork", [_tool_entry("git fetch upstream", True)])
    text = render(memory.recall("sync the fork"))
    assert text is not None
    assert "sync the fork" in text and "git fetch upstream" in text
    assert "may or may not apply" in text
    assert render([]) is None


# --- the prompt ---------------------------------------------------------------------


def test_the_prelude_goes_in_the_user_message_and_the_system_prompt_is_unchanged() -> None:
    box = build_sandbox(VARIANT_SEED, ["diverged"])
    try:
        signature = TaskSignature(
            intent="Reconcile this branch with upstream.",
            fingerprint=StateFingerprint.observe(box),
            target=str(box.work),
        )
        provider = FakeProvider(_finish())
        _, transcript = solve(signature, box, provider, prelude="NOTES")
    finally:
        box.destroy()
    assert provider.calls[0]["system"] == SYSTEM_PROMPT
    assert transcript[1]["content"] == "NOTES\n\nReconcile this branch with upstream."


def test_arm_1_without_a_prelude_sends_the_task_alone() -> None:
    box = build_sandbox(VARIANT_SEED, ["diverged"])
    try:
        signature = TaskSignature(
            intent="Reconcile this branch with upstream.",
            fingerprint=StateFingerprint.observe(box),
            target=str(box.work),
        )
        _, transcript = solve(signature, box, FakeProvider(_finish()))
    finally:
        box.destroy()
    assert transcript[1]["content"] == "Reconcile this branch with upstream."


# --- the model's verdict, never the checker's --------------------------------------------


def test_a_declared_but_wrong_episode_is_remembered(tmp_path: Path) -> None:
    """The model says done after a no-op; the checker fails it; memory keeps it anyway."""
    memory = SuccessMemory()
    record = run_episode(
        Arm.REACT_MEMORY,
        "diverged",
        VARIANT_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(_tool("git status"), _finish()),
        library=Library(tmp_path / "lib", evaluate_preconditions=evaluate_preconditions),
        model="fake",
        memory=memory,
    )
    assert record.outcome is EpisodeOutcome.SUCCESS, "the model declared it done"
    assert record.succeeded is False, "the checker disagrees"
    assert len(memory) == 1, "1b remembers by the model's verdict, never the checker's"
    assert record.memory_recalled == 0


def test_a_failed_episode_is_not_remembered(tmp_path: Path) -> None:
    memory = SuccessMemory()
    record = run_episode(
        Arm.REACT_MEMORY,
        "diverged",
        VARIANT_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=FakeProvider(raises=RuntimeError("provider down")),
        library=Library(tmp_path / "lib", evaluate_preconditions=evaluate_preconditions),
        model="fake",
        memory=memory,
    )
    assert record.outcome is EpisodeOutcome.FAIL
    assert len(memory) == 0


def test_run_episode_refuses_1b_without_a_memory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SuccessMemory"):
        run_episode(
            Arm.REACT_MEMORY,
            "diverged",
            VARIANT_SEED,
            1,
            role=OccurrenceRole.VARIANT,
            provider=FakeProvider(),
            library=Library(tmp_path / "lib"),
            model="fake",
        )


# --- end to end -------------------------------------------------------------------


def test_1b_runs_arm_1s_plan_and_its_second_episode_sees_its_first(tmp_path: Path) -> None:
    provider = FakeProvider(*(_merge_solve() * 4))  # arm 1 twice, then 1b twice
    out = run_benchmark(
        arms=[Arm.REACT, Arm.REACT_MEMORY],
        faults=["diverged"],
        occurrences=2,
        seeds=[VARIANT_SEED, REPLAY_SEED],
        out=tmp_path / "ledger.jsonl",
        model="fake",
        provider=provider,
    )
    rows = read(out)
    plan = {
        arm: [(r.fault_type, r.seed, r.occurrence_index) for r in rows if r.arm is arm]
        for arm in (Arm.REACT, Arm.REACT_MEMORY)
    }
    assert plan[Arm.REACT] == plan[Arm.REACT_MEMORY], "1b runs the identical plan"

    react_rows = [r for r in rows if r.arm is Arm.REACT]
    memory_rows = [r for r in rows if r.arm is Arm.REACT_MEMORY]
    assert [r.memory_recalled for r in react_rows] == [None, None]
    assert [r.memory_recalled for r in memory_rows] == [0, 1]
    assert all(r.admission_gate is None for r in memory_rows), "1b has no library"

    # Calls 0-5 are arm 1; 6-8 are 1b's first episode; 9 opens 1b's second.
    def user_message(call: dict) -> str:
        return next(m["content"] for m in call["messages"] if m["role"] == "user")

    assert all("Notes from tasks" not in user_message(call) for call in provider.calls[:9])
    second = user_message(provider.calls[9])
    assert "Notes from tasks" in second
    assert "git merge --no-edit upstream/main" in second


def test_1b_is_refused_in_a_frozen_run(tmp_path: Path) -> None:
    root = tmp_path / "frozen"
    store_programs(
        root,
        [
            p.model_copy(update={"status": ProgramStatus.ADMITTED})
            for p in gold_programs("sync_fork_with_upstream")
        ],
    )
    with pytest.raises(ValueError, match="online mode"):
        run_benchmark(
            arms=[Arm.REACT_MEMORY],
            faults=["diverged"],
            occurrences=1,
            seeds=[VARIANT_SEED],
            out=tmp_path / "ledger.jsonl",
            model="fake",
            provider=FakeProvider(),
            frozen_library=root,
        )
