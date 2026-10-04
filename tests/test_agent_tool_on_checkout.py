"""The agent's git tool on an existing checkout runs like every model-authored command there.

On a harness sandbox the agent's `run_git` tool calls git directly: the remote is a
local path, and the measurements ran that way. On a checkout (#181) the remote is real
and on the network, so a solve there -- #188's learning path -- must not reach it. These
tests pin that, on a checkout, a tool call:

* goes through `runtime.confine.run_confined` under `sandbox.run_env`, and on a harness
  sandbox it does not (the measured path is unchanged);
* fetches from the trusted pre-fetch's mirror, with the real remote gone;
* commits as the repository's owner, not as the sandbox identity;
* still passes the tool's own refusals before anything runs.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from conftest import FakeProvider

from precondition_library.agents import react
from precondition_library.checkout import open_checkout
from precondition_library.program import EpisodeOutcome
from precondition_library.provider import Completion, TokenUsage
from precondition_library.sandbox import run_git
from precondition_library.signatures import StateFingerprint, TaskSignature
from precondition_library.tasks.faults import build_sandbox

USER = ("Repo Owner", "owner@example.invalid")
_USAGE = TokenUsage(tokens_in=1, tokens_out=1, uncached_tokens_in=1)
_IDS = itertools.count(1)


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def behind(tmp_path):
    """A clone one commit behind `origin/trunk`, opened as a checkout; the origin moved away."""
    origin = tmp_path / "origin.git"
    run_git(("-c", "init.defaultBranch=trunk", "init", "-q", "--bare", str(origin)), cwd=tmp_path)
    seed = tmp_path / "seed"
    run_git(("clone", "-q", str(origin), str(seed)), cwd=tmp_path)
    _git(seed, "checkout", "-q", "-b", "trunk")
    _commit(seed, "first")
    _git(seed, "push", "-q", "origin", "trunk")
    work = tmp_path / "work"
    run_git(("clone", "-q", str(origin), str(work)), cwd=tmp_path)
    _git(work, "config", "user.name", USER[0])
    _git(work, "config", "user.email", USER[1])
    tip = _commit(seed, "second")
    _git(seed, "push", "-q", "origin", "trunk")

    env = open_checkout(work, scratch=tmp_path)
    origin.rename(origin.with_name("moved-away.git"))  # the real remote is unreachable now
    yield env, tip
    env.destroy()


def test_a_checkout_tool_call_is_confined_and_a_harness_one_is_not(behind, monkeypatch) -> None:
    env, _ = behind
    calls: list[dict] = []
    real = react.run_confined

    def spy(argv, *, cwd, env, timeout_s):
        calls.append({"argv": argv, "env": env})
        return real(argv, cwd=cwd, env=env, timeout_s=timeout_s)

    monkeypatch.setattr(react, "run_confined", spy)
    text, ok = react._run_tool("git status", env)
    assert ok, text
    (call,) = calls
    assert call["argv"] == ["git", "status"]
    assert "url." in " ".join(call["env"].get(f"GIT_CONFIG_KEY_{i}", "") for i in range(16))

    box = build_sandbox(0, [])
    try:
        text, ok = react._run_tool("git status", box)
        assert ok, text
        assert len(calls) == 1, "the harness path still calls git directly, as measured"
    finally:
        box.destroy()


def test_the_agent_fetches_from_the_mirror_with_the_remote_gone(behind) -> None:
    env, tip = behind
    text, ok = react._run_tool("git fetch origin", env)
    assert ok, text
    text, ok = react._run_tool("git merge --ff-only origin/trunk", env)
    assert ok, text
    assert _git(env.work, "rev-parse", "HEAD") == tip


def test_an_agent_commit_on_a_checkout_is_the_owners(behind) -> None:
    env, _ = behind
    text, ok = react._run_tool("git commit -q --allow-empty -m from-the-agent", env)
    assert ok, text
    assert _git(env.work, "log", "-1", "--format=%an|%ae") == "|".join(USER)


def test_refusals_still_come_first_on_a_checkout(behind, monkeypatch) -> None:
    env, _ = behind
    monkeypatch.setattr(react, "run_confined", lambda *a, **k: pytest.fail("must not run"))
    for command in ("ls", "git status && git log", "git -c core.hooksPath=/tmp status"):
        text, ok = react._run_tool(command, env)
        assert not ok and text.startswith("refused:"), command


def _call(name: str, **arguments: str) -> dict:
    return {
        "id": f"call_{next(_IDS)}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_a_whole_solve_on_a_checkout_syncs_it_without_the_network(behind) -> None:
    env, tip = behind
    provider = FakeProvider(
        Completion(
            tool_calls=[
                _call("run_git", command="git fetch origin"),
                _call("run_git", command="git merge --ff-only origin/trunk"),
            ],
            usage=_USAGE,
            model="fake",
        ),
        Completion(
            tool_calls=[_call(react.FINISH_TOOL, summary="synced")], usage=_USAGE, model="fake"
        ),
    )
    state = StateFingerprint(
        dirty_worktree=False,
        branch="trunk",
        upstream_ahead=1,
        upstream_behind=0,
        has_locked_branch=False,
        has_submodule_reference=False,
    )
    signature = TaskSignature(intent="sync with upstream", fingerprint=state, target=str(env.work))
    outcome, transcript = react.solve(signature, env, provider)
    assert outcome is EpisodeOutcome.SUCCESS, transcript
    assert _git(env.work, "rev-parse", "HEAD") == tip
