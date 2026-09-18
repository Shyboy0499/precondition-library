"""The sandbox environment is allowlisted, not inherited.

`git_env` used to start from `dict(os.environ)`, which handed the operator's
whole environment -- including any API key exported for the run -- to
model-authored code. The spec claims the environment is scrubbed (§9), so these
tests pin the mechanism rather than a constant: a sentinel set in *this* process
must be invisible to a command run under the sandbox environment.

Asserting on `git_env()`'s output and on a real subprocess is deliberate. A test
that only inspected `_ALLOWLISTED_ENV_VARS` would keep passing if a future edit
reintroduced an `os.environ` spread beside it, which is exactly the regression
these exist to catch.
"""

from __future__ import annotations

import subprocess

from precondition_library.runtime.probes import SHELL
from precondition_library.sandbox import git_env

SENTINEL = "SMOKE_SECRET"
"""A variable the test process exports; no sandbox command may see it."""

_SENTINEL_VALUE = "sk-live-do-not-hand-to-generated-code"


def test_git_env_is_an_allowlist_not_the_callers_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(SENTINEL, _SENTINEL_VALUE)
    monkeypatch.setenv("DEEPSEEK_API_KEY", _SENTINEL_VALUE)

    env = git_env(home=tmp_path)

    assert SENTINEL not in env, "the sandbox environment inherited the sentinel"
    assert "DEEPSEEK_API_KEY" not in env, "an API key must not reach generated code"
    assert env["HOME"] == str(tmp_path), "HOME must be redirected into the sandbox"
    assert "PATH" in env, "git and the probes are found through PATH"


def test_a_command_under_the_sandbox_environment_cannot_read_the_sentinel(
    monkeypatch, tmp_path
) -> None:
    """The falsifiable half: run a real command with the environment git_env builds."""
    monkeypatch.setenv(SENTINEL, _SENTINEL_VALUE)

    # `SHELL`, not a hardcoded "bash": a bare `bash` is the WSL launcher on
    # Windows, so this would return non-zero for a reason unrelated to the
    # environment it is testing -- and would keep doing so after `SHELL` was
    # fixed, because this line bypasses it.
    completed = subprocess.run(
        [*SHELL, f'printenv {SENTINEL} || echo "<unset>"'],
        env=git_env(home=tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "<unset>", (
        f"a command under git_env read {SENTINEL}: {completed.stdout!r}"
    )


def test_home_is_omitted_when_the_caller_has_no_sandbox_to_redirect_into(monkeypatch) -> None:
    """`git_env()` must not leak the operator's HOME; it leaves it unset instead."""
    monkeypatch.setenv("HOME", "/home/the-operator")

    assert "HOME" not in git_env()
