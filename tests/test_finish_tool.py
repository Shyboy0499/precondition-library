"""The agent declares done with a `finish` tool, and is told once when its budget is nearly out.

The second live run (#171) found the model never ending a turn without a tool call: it
fixed the repository, then kept verifying until the turn or tool-call budget ran out, so
3 of 5 failed build episodes failed with the checker already passing. These tests pin:

* `finish` ends the solve with `SUCCESS`, the agent's own declaration, and is not a
  command: it neither runs nor counts toward the tool-call budget;
* calls batched before `finish` in the same turn run, and calls after it do not;
* one budget reminder is sent, as a user message, before the turn that may be the last
  -- by turns or by tool calls -- and it says nothing about whether the repository is
  right;
* a reply with no tool call still ends the solve, as before.
"""

from __future__ import annotations

import itertools
import json

from conftest import FakeProvider

from precondition_library.agents.react import (
    BUDGET_NUDGE,
    FINISH_TOOL,
    SYSTEM_PROMPT,
    available_tools,
    solve,
)
from precondition_library.program import EpisodeOutcome
from precondition_library.provider import Completion, TokenUsage
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox

SEED = 1
_IDS = itertools.count(1)
_USAGE = TokenUsage(tokens_in=10, tokens_out=5, uncached_tokens_in=10)


def _call(name: str, **arguments: str) -> dict:
    return {
        "id": f"call_{next(_IDS)}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _turn(*calls: dict) -> Completion:
    return Completion(tool_calls=list(calls), usage=_USAGE, model="fake")


def _git(command: str) -> dict:
    return _call("run_git", command=command)


def _finish(summary: str = "synced with upstream") -> dict:
    return _call(FINISH_TOOL, summary=summary)


def _solve(provider: FakeProvider, **kwargs):
    box = build_sandbox(SEED, ["diverged"])
    try:
        signature = TaskSignature(
            intent="sync", fingerprint=StateFingerprint.observe(box), target=str(box.work)
        )
        return solve(signature, box, provider, **kwargs)
    finally:
        box.destroy()


def _tool_entries(transcript: list[dict]) -> list[dict]:
    return [entry for entry in transcript if entry["role"] == "tool"]


def test_the_agent_is_offered_finish_and_told_to_use_it() -> None:
    names = [tool["function"]["name"] for tool in available_tools()]
    assert names == ["run_git", FINISH_TOOL]
    assert "`finish`" in SYSTEM_PROMPT


def test_finish_ends_the_solve_as_the_agents_own_declaration() -> None:
    provider = FakeProvider(_turn(_git("git status")), _turn(_finish("fast-forwarded")))
    outcome, transcript = _solve(provider)

    assert outcome is EpisodeOutcome.SUCCESS
    assert transcript[-1] == {"role": "assistant", "content": "fast-forwarded", "done": True}
    assert len(_tool_entries(transcript)) == 1, "finish is a declaration, not a command"


def test_calls_before_finish_in_a_turn_run_and_calls_after_it_do_not() -> None:
    provider = FakeProvider(_turn(_git("git status"), _finish(), _git("git log")))
    outcome, transcript = _solve(provider)

    assert outcome is EpisodeOutcome.SUCCESS
    assert [entry["command"] for entry in _tool_entries(transcript)] == ["git status"]


def test_finish_is_accepted_even_when_the_tool_call_budget_is_spent() -> None:
    """Declaring done is not a command, so a spent budget does not refuse it."""
    provider = FakeProvider(_turn(_git("git status"), _git("git log"), _finish()))
    outcome, _ = _solve(provider, max_tool_calls=2)
    assert outcome is EpisodeOutcome.SUCCESS


def test_one_reminder_is_sent_before_the_last_turn() -> None:
    provider = FakeProvider(*[_turn(_git("git status")) for _ in range(4)])
    outcome, transcript = _solve(provider, max_steps=4)

    assert outcome is EpisodeOutcome.FAIL
    nudges = [i for i, entry in enumerate(transcript) if entry.get("nudge")]
    assert len(nudges) == 1
    assert transcript[nudges[0]] == {"role": "user", "content": BUDGET_NUDGE, "nudge": True}
    later_turns = [e for e in transcript[nudges[0] :] if e["role"] == "assistant"]
    assert len(later_turns) == 1, "it comes before the last turn, not earlier"
    assert provider.calls[-1]["messages"][-1]["content"] == BUDGET_NUDGE, "the model sees it"


def test_the_reminder_also_fires_when_tool_calls_are_nearly_spent() -> None:
    provider = FakeProvider(
        _turn(*[_git("git status") for _ in range(20)]),
        _turn(_finish()),
    )
    outcome, transcript = _solve(provider, max_steps=12, max_tool_calls=24)

    assert outcome is EpisodeOutcome.SUCCESS
    assert sum(1 for entry in transcript if entry.get("nudge")) == 1


def test_a_short_solve_gets_no_reminder_and_a_plain_reply_still_finishes() -> None:
    provider = FakeProvider(
        _turn(_git("git status")),
        Completion(text="done", usage=_USAGE, model="fake"),
    )
    outcome, transcript = _solve(provider)

    assert outcome is EpisodeOutcome.SUCCESS
    assert not any(entry.get("nudge") for entry in transcript)


def test_the_reminder_reveals_nothing_about_the_repository() -> None:
    """It is one fixed sentence about budget, never a verdict on the work."""
    lowered = BUDGET_NUDGE.lower()
    for word in ("correct", "succeeded", "checker", "passes", "fixed"):
        assert word not in lowered
