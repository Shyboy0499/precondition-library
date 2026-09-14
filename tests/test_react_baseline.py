"""Arm 1 end to end: real sandbox, scripted model, git-only grading.

Everything here is offline. The model is `FakeProvider`, which returns queued
completions and records every call; the environment is a real `dirty_tree`
sandbox with the pinned git environment; the verdict comes from the fault's own
checker and is never consulted by `solve`.

The two negative controls are the point. A baseline that cannot solve the fault
would make the arm comparison empty, so one test scripts the commands that
genuinely resolve it and requires the checker to pass. A baseline that stopped
on the ground-truth checker would be reporting the oracle's verdict rather than
the agent's, so another test scripts a model that inspects the tree, declares
itself finished, and fixes nothing, and requires `solve` to both stop on that
declaration and return a non-SUCCESS outcome while the checker still says no.
"""

from __future__ import annotations

import json

import pytest
from conftest import FakeProvider

from precondition_library.agents.react import SYSTEM_PROMPT, available_tools, solve
from precondition_library.program import EpisodeOutcome
from precondition_library.provider import Completion, ProviderError, TokenUsage
from precondition_library.sandbox import Sandbox, create
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults.dirty_tree import SPEC

# Both halves of the fault's seed space: 0 injects the tracked edit alone, 3 adds
# the untracked file (see `state_for_seed`). Solving only one half would not show
# the baseline can handle the branchy state the fault exists to model.
SEEDS = [0, 3]
MODIFIED_ONLY = 0


def _completion(action: dict) -> Completion:
    return Completion(
        text=json.dumps(action), usage=TokenUsage(tokens_in=10, tokens_out=5), model="fake"
    )


def _tool(command: str) -> Completion:
    return _completion({"tool": "run_git", "arguments": {"command": command}})


def _finish() -> Completion:
    return _completion({"done": True})


def _signature(box: Sandbox, seed: int = MODIFIED_ONLY) -> TaskSignature:
    """A real signature: the fault's request plus the environment's fingerprint."""
    return TaskSignature(
        intent=SPEC.task_text(seed),
        fingerprint=StateFingerprint.observe(box),
        target=str(box.work),
    )


@pytest.fixture
def make_sandbox():
    """Build injected sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int = MODIFIED_ONLY) -> Sandbox:
        box = create(seed, ["dirty_tree"])
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def test_loop_runs_a_tool_and_finishes(make_sandbox) -> None:
    """One command, then a declaration: the transcript records both, in order."""
    box = make_sandbox()
    fake = FakeProvider(_tool("git status --porcelain"), _finish())
    _, transcript = solve(_signature(box), box, fake)

    assert [entry["role"] for entry in transcript] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert transcript[0]["content"] == SYSTEM_PROMPT
    assert transcript[1]["content"] == SPEC.task_text(MODIFIED_ONLY)
    call = transcript[2]["tool_call"]
    assert call["name"] == "run_git"
    assert call["arguments"]["command"] == "git status --porcelain"
    assert transcript[3]["command"] == "git status --porcelain"
    assert transcript[3]["ok"] is True
    assert transcript[3]["content"].startswith("exit code: 0")
    # The dirty tree is actually observed, not merely echoed back by the fake.
    assert "docs/readme.md" in transcript[3]["content"]
    assert transcript[4]["done"] is True
    assert fake.calls[0]["tools"] == available_tools()


def test_a_claim_of_finish_is_not_a_pass(make_sandbox) -> None:
    """The stopping-rule control: declaring done ends the loop, it does not grade it.

    The scripted model looks at the tree and declares itself finished while the
    fault is untouched. `solve` must stop on the declaration (last turn is
    `done`, and no checker was consulted -- none is imported here) and return a
    non-SUCCESS outcome; the independent checker must still say not-ok. A solve
    that stopped on the checker would be reporting the oracle.
    """
    box = make_sandbox()
    fake = FakeProvider(_tool("git status --porcelain"), _finish())
    outcome, transcript = solve(_signature(box), box, fake)

    assert outcome is not EpisodeOutcome.SUCCESS
    assert transcript[-1]["done"] is True
    assert len(fake.calls) == 2
    result = SPEC.check(box)
    assert result.ok is False
    assert result.detail


@pytest.mark.parametrize("seed", SEEDS)
def test_scripted_commands_genuinely_resolve_the_fault(seed: int, make_sandbox) -> None:
    """A baseline that cannot solve the fault would make the comparison empty.

    The shortest honest resolution, run through the tool exactly as a model
    would call it: set the work aside, sync, put it back. The fault's own
    checker -- not `solve` -- is what confirms it.
    """
    box = make_sandbox(seed)
    fake = FakeProvider(
        _tool("git stash push -u -m pl-react"),
        _tool("git fetch -q upstream"),
        _tool("git rebase upstream/main"),
        _tool("git stash pop"),
        _finish(),
    )
    _, transcript = solve(_signature(box, seed), box, fake)

    assert len(fake.calls) == 5
    tool_entries = [entry for entry in transcript if entry["role"] == "tool"]
    assert len(tool_entries) == 4
    assert all(entry["ok"] for entry in tool_entries), [entry["content"] for entry in tool_entries]
    result = SPEC.check(box)
    assert result.ok, result.detail


def test_a_non_git_command_is_refused_as_a_tool_result(make_sandbox) -> None:
    """A refusal is information for the model, not a crash for the episode."""
    box = make_sandbox()
    fake = FakeProvider(_tool("rm -rf /tmp/x"), _finish())
    _, transcript = solve(_signature(box), box, fake)

    tool_entry = next(entry for entry in transcript if entry["role"] == "tool")
    assert "refused" in tool_entry["content"].lower()
    assert tool_entry["ok"] is False
    # The loop continued and the model could correct itself.
    assert transcript[-1]["done"] is True


def test_max_steps_bounds_the_loop(make_sandbox) -> None:
    """A model that never finishes is cut off, and the transcript shows where."""
    box = make_sandbox()
    fake = FakeProvider(*[_tool("git status --porcelain") for _ in range(3)])
    outcome, transcript = solve(_signature(box), box, fake, max_steps=3)

    assert outcome is EpisodeOutcome.FAIL
    assert len(fake.calls) == 3
    assert sum(entry["role"] == "assistant" for entry in transcript) == 3
    # system + task + 3 x (assistant, tool) + the budget note.
    assert len(transcript) == 2 + 2 * 3 + 1
    assert "budget" in transcript[-1]["content"]


def test_provider_error_is_recorded_not_swallowed(make_sandbox) -> None:
    """Spec §8: a provider error is a FAIL that still carries its reason."""
    box = make_sandbox()
    fake = FakeProvider(raises=ProviderError("simulated outage"))
    outcome, transcript = solve(_signature(box), box, fake)

    assert outcome is EpisodeOutcome.FAIL
    assert len(fake.calls) == 1
    errors = [entry for entry in transcript if entry["role"] == "error"]
    assert errors
    assert "simulated outage" in errors[-1]["content"]
    assert "ProviderError" in errors[-1]["content"]
