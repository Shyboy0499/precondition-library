"""Per-invocation git config overrides cannot undo the hardening (issue #159).

`sandbox._GIT_HARDENING` is pinned through the environment, and command-line config
wins over it: `git -c core.hooksPath=<dir>` ran a committed hook under the hardened
environment. These tests pin the fix -- one parser shared by the replay guard and the
ReAct tool, an allowlist of exactly one harmless override, and refusal of a body that
re-sets the `GIT_CONFIG_*` variables itself -- and that the parser does not mistake a
subcommand's own `-c` (`git log -c`) for config.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from precondition_library.agents.react import _run_tool
from precondition_library.runtime.guard import Verdict, screen
from precondition_library.sandbox import (
    ALLOWED_GIT_CONFIG_OVERRIDES,
    create,
    disallowed_git_config_overrides,
    git_config_overrides,
    git_env,
)


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (["git", "-c", "core.hooksPath=h", "commit"], ["core.hooksPath=h"]),
        (["git", "-c", "a=1", "-c", "b=2", "status"], ["a=1", "b=2"]),
        (["git", "--config-env=core.editor=E", "commit"], ["config-env:core.editor=E"]),
        (["git", "--config-env", "core.editor=E", "commit"], ["config-env:core.editor=E"]),
        (["git", "-C", "dir", "-c", "x=y", "status"], ["x=y"]),
        (["git", "submodule", "foreach", "git", "-c", "x=y", "fetch"], ["x=y"]),
        (["git", "submodule", "foreach", "git -c x=y fetch"], ["x=y"]),
        (["/usr/bin/git", "-c", "x=y", "status"], ["x=y"]),
        (["git", "log", "-c", "--stat"], []),
        (["git", "show", "-c", "HEAD"], []),
        (["bash", "-c", "echo hi"], []),
    ],
)
def test_only_global_options_count_as_config(tokens, expected) -> None:
    assert git_config_overrides(tokens) == expected


def test_the_allowlist_is_local_file_transport_alone() -> None:
    assert ALLOWED_GIT_CONFIG_OVERRIDES == frozenset({"protocol.file.allow=always"})
    allowed = ["git", "-c", "protocol.file.allow=always", "submodule", "update", "--init"]
    assert disallowed_git_config_overrides(allowed) == []
    # Keys are case-insensitive in git, so the casing trick does not slip through.
    assert disallowed_git_config_overrides(["git", "-c", "core.HooksPath=h", "commit"])


@pytest.mark.parametrize(
    "body",
    [
        "git -c core.hooksPath=.githooks commit -m x",
        "git -c core.fsmonitor=./evil status",
        "git -c core.sshCommand=./evil fetch origin",
        "git -c alias.x='!sh evil' x",
        "git --config-env=core.hooksPath=EVIL commit -m x",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=h git commit -m x",
        "export GIT_CONFIG_PARAMETERS=\"'core.hookspath'='h'\"\ngit commit -m x",
        "GIT_CONFIG_GLOBAL=./evil.cfg git commit -m x",
        "git submodule foreach git -c core.fsmonitor=evil status",
        "git submodule foreach 'git -c core.sshCommand=evil fetch'",
    ],
)
def test_the_guard_refuses_every_override_form(body: str) -> None:
    decision = screen(body, env_root="/work")
    assert decision.verdict is Verdict.REFUSE
    assert "git config override" in decision.reason


@pytest.mark.parametrize(
    "body",
    [
        "git -c protocol.file.allow=always submodule update --init",
        "git log -c --stat",
        "git commit -m x",
        "git config user.name sandbox",
    ],
)
def test_the_guard_allows_the_allowlist_and_non_config_uses_of_c(body: str) -> None:
    assert screen(body, env_root="/work").verdict is Verdict.ALLOW


def test_the_react_tool_refuses_an_override_and_runs_the_allowlisted_one() -> None:
    box = create(0, [])
    try:
        refused, ok = _run_tool("git -c core.hooksPath=/tmp/h status", box)
        assert ok is False and "not allowed" in refused
        ran, ok = _run_tool("git -c protocol.file.allow=always status", box)
        assert ok is True, ran
    finally:
        box.destroy()


def test_a_persistent_repo_config_write_does_not_beat_the_hardening() -> None:
    """Why only per-invocation overrides need refusing: repo config is outranked."""
    work = Path(tempfile.mkdtemp(prefix="hardening-"))
    env = git_env(home=work)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, env=env, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    hooks = work / "hooks"
    hooks.mkdir()
    marker = work.parent / f"{work.name}-hook-ran"
    (hooks / "pre-commit").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (hooks / "pre-commit").chmod(0o755)
    git("config", "core.hooksPath", str(hooks))
    (work / "f").write_text("x")
    git("add", "f")
    git("commit", "-qm", "x")
    assert not marker.exists()
