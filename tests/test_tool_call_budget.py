"""The agent's budget counts commands, and only a declared success is compiled (#160).

The first live run found a model batching 4-5 tool calls per turn, so a 12-turn budget
let one episode run about 45 commands; it also found transcripts the agent never
declared finished compiled and admitted. These tests pin the owner's choices:

* `solve` stops after `DEFAULT_MAX_TOOL_CALLS` tool calls however they are batched;
* every row records the tool calls its agent ran; and
* a fallback is compiled only when the agent itself declared the task done -- the
  agent's verdict, never the checker's.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from conftest import FakeProvider

from precondition_library.agents.react import DEFAULT_MAX_TOOL_CALLS, solve
from precondition_library.bench.ledger import Arm, OccurrenceRole
from precondition_library.bench.run import run_episode
from precondition_library.library import Library
from precondition_library.program import EpisodeOutcome
from precondition_library.provider import Completion, TokenUsage
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox

DISCARD_SEED = 1
_IDS = itertools.count(1)
_USAGE = TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10)


def _batch(*commands: str) -> Completion:
    """One model turn that requests several tool calls at once."""
    calls = [
        {
            "id": f"call_{next(_IDS)}",
            "type": "function",
            "function": {"name": "run_git", "arguments": json.dumps({"command": command})},
        }
        for command in commands
    ]
    return Completion(tool_calls=calls, usage=_USAGE, model="fake")


def _not_done() -> Completion:
    """A last word that does not declare the task done (issue #179)."""
    return Completion(text="not done yet", usage=_USAGE, model="fake")


def _finish() -> Completion:
    return Completion(text="done", usage=_USAGE, model="fake")


def test_the_cap_is_twice_the_turn_budget() -> None:
    assert DEFAULT_MAX_TOOL_CALLS == 24


def test_a_batched_turn_cannot_run_past_the_tool_call_budget() -> None:
    box = build_sandbox(DISCARD_SEED, ["diverged"])
    try:
        signature = TaskSignature(
            intent="sync", fingerprint=StateFingerprint.observe(box), target=str(box.work)
        )
        provider = FakeProvider(_batch(*["git status"] * 30), _not_done())
        outcome, transcript = solve(signature, box, provider)
    finally:
        box.destroy()
    assert outcome is EpisodeOutcome.FAIL
    tools = [entry for entry in transcript if entry["role"] == "tool"]
    assert sum(1 for entry in tools if not entry.get("not_run")) == DEFAULT_MAX_TOOL_CALLS
    assert sum(1 for entry in tools if entry.get("not_run")) == 30 - DEFAULT_MAX_TOOL_CALLS, (
        "every call past the cap is answered, not run, so the conversation stays valid"
    )
    assert "tool-call budget of 24 spent" in transcript[-1]["content"]
    assert len(provider.calls) == 2, "one turn was enough to exhaust it; then the last word"


def test_every_row_records_the_tool_calls_its_agent_ran(tmp_path: Path) -> None:
    provider = FakeProvider(
        _batch("git fetch -q upstream", "git reset --hard upstream/main"), _finish()
    )
    record = run_episode(
        Arm.REACT,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=Library(tmp_path / "lib"),
        model="fake",
    )
    assert record.llm_calls == 2, "one batched turn and one finish"
    assert record.tool_calls == 2, "but two commands ran"
    assert record.succeeded is True


def test_a_failed_solve_is_not_compiled(tmp_path: Path) -> None:
    """The agent never declared done, so no compile call is made or charged."""
    provider = FakeProvider(_batch(*["git status"] * 30), _not_done())  # no compile queued
    record = run_episode(
        Arm.PRECONDITION,
        "diverged",
        DISCARD_SEED,
        1,
        role=OccurrenceRole.VARIANT,
        provider=provider,
        library=Library(tmp_path / "lib", evaluate_preconditions=evaluate_preconditions),
        model="fake",
    )
    assert record.outcome is EpisodeOutcome.FAIL
    assert record.tool_calls == 24, "the calls past the cap were not run, so not counted"
    assert len(provider.calls) == 2, "the solve and its last word; no compile call followed"
    assert record.compile_failure_reason is None
    assert record.admitted is None
    assert Library(tmp_path / "lib").load_all() == []
