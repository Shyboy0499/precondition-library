"""The agent's git tool refuses the ways git runs a command itself.

The tool runs one git command with no shell, but in the fourth live smoke run the agent
set `alias.lockfix` to `!sed -i ...` and ran `git lockfix`, so `sed` ran on the host.
These tests pin that every form `agents.command_screen` names is refused, that the
commands the live agent actually ran to read and repair config still run, and, end to
end, that the alias pair from that transcript now runs nothing.
"""

from __future__ import annotations

import shlex

import pytest

from precondition_library.agents.command_screen import command_running_reason
from precondition_library.agents.react import _run_tool
from precondition_library.sandbox import git_invocation

LIVE_ALIAS = (
    "git config alias.lockfix \"!sed -i -e 's/version = 0.9.5/version = 3.4.0/' deps.lock\""
)
"""The alias the live agent set in the fourth smoke run, shortened to one sed expression."""


@pytest.mark.parametrize(
    "command",
    [
        LIVE_ALIAS,
        "git config --add alias.x '!touch ran'",
        "git config set alias.x 'log --oneline'",
        "git config Alias.x '!touch ran'",
        "git config filter.lock.clean 'touch ran'",
        "git config diff.lock.textconv 'touch ran'",
        "git config merge.lock.driver 'touch ran'",
        "git config core.editor 'touch ran'",
        "git config core.sshCommand 'touch ran'",
        "git config remote.upstream.uploadpack 'touch ran; git-upload-pack'",
        "git config include.path ../elsewhere",
        "git config submodule.lib.update '!touch ran'",
        "git config --file .gitmodules alias.x '!touch ran'",
        "git config --edit",
        "git config --rename-section lock alias",
        "git submodule foreach 'touch ran'",
        "git submodule --quiet foreach 'touch ran'",
        "git bisect run make",
        "git filter-branch --tree-filter 'touch ran' HEAD",
        "git difftool HEAD~1",
        "git mergetool",
        "git rebase --exec 'touch ran' upstream/main",
        "git rebase --exec='touch ran' upstream/main",
        "git rebase -x 'touch ran' upstream/main",
        "git rebase -ix 'touch ran' upstream/main",
        "git fetch --upload-pack='touch ran; git-upload-pack' upstream",
        "git pull --upload-pack 'touch ran' upstream main",
        "git ls-remote -u 'touch ran' upstream",
        "git clone --template=/tmp/hooks upstream copy",
        "git clone -c alias.x=!y upstream copy",
        "git init --template=/tmp/hooks",
        "git push --receive-pack='touch ran' upstream main",
        "git archive --remote=upstream --exec='touch ran' HEAD",
        "git grep -O 'touch ran' version",
        "git grep --open-files-in-pager=vim version",
        "git --exec-path=/tmp/bin status",
    ],
)
def test_a_command_git_would_run_is_refused(command: str) -> None:
    assert command_running_reason(shlex.split(command)) is not None, command


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git --exec-path",
        "git config --list --show-origin",
        "git config --list --local",
        "git config --get-regexp submodule",
        "git config --get-regexp '^branch'",
        "git config --get pull.rebase",
        "git config --file .gitmodules --list",
        "git config -f .gitmodules --get-regexp 'submodule'",
        "git config --remove-section submodule.vendor/libcore",
        "git config --unset branch.main.rebase",
        "git config branch.main.merge",
        "git config branch.main.merge refs/heads/trunk",
        "git config BRANCH.main.MERGE refs/heads/trunk",
        "git config set branch.main.remote upstream",
        "git config branch.feature/x.merge refs/heads/x",
        "git config submodule.vendor/libcore.url ../libcore.git",
        "git config submodule.vendor/libcore.update rebase",
        "git config --file .gitmodules submodule.vendor/libcore.url ../libcore.git",
        "git config user.email agent@example.invalid",
        "git config pull.rebase false",
        "git config merge.conflictStyle diff3",
        "git rebase upstream/main",
        "git rebase --onto upstream/main HEAD~1",
        "git fetch upstream",
        "git submodule update --init --recursive",
        "git submodule status",
        "git bisect start",
        "git grep -n version",
        "git log -c",
        "git clone upstream copy",
    ],
)
def test_ordinary_repository_work_still_runs(command: str) -> None:
    assert command_running_reason(shlex.split(command)) is None, command


def test_the_subcommand_follows_the_global_options() -> None:
    assert git_invocation(["git", "-c", "a=b", "--no-pager", "log", "-1"]) == (
        ["-c", "a=b", "--no-pager"],
        "log",
        ["-1"],
    )
    assert git_invocation(["git", "--version"]) == (["--version"], None, [])


def test_the_live_alias_pair_now_runs_nothing(make_sandbox) -> None:
    box = make_sandbox(0, [])
    witness = box.work / "ran"
    for command in ("git config alias.probe '!touch ran'", "git probe"):
        result, ok = _run_tool(command, box)
        if command.startswith("git config"):
            assert not ok and result.startswith("refused:"), result
            assert "may name a command" in result
    assert not witness.exists(), "the alias ran a command on the host"
    alias, _ = _run_tool("git config --get alias.probe", box)
    assert alias == "exit code: 1", "the alias was never written"
