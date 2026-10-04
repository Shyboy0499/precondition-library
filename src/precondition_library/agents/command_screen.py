"""What the agent's git tool refuses because git itself would run a command.

`react.run_git`'s tool runs one git command with no shell, and that is what makes
`rm -rf ...` a refusal rather than an execution. **git can run a command on its own,
though**, and a tool that passes any `git ...` line inherits every way it does:

* **Persistent config that names a command.** In the fourth live smoke run the agent,
  given no way to write a file, ran
  `git config alias.lockfix "!sed -i ... deps.lock"` and then `git lockfix`. The alias
  ran `sed` through a shell on the host. Filter, diff and merge drivers,
  `core.editor`, `remote.<name>.uploadpack`, `include.path` and a `!`-valued
  `submodule.<name>.update` run commands the same way. `sandbox._GIT_HARDENING` pins
  only hooks, fsmonitor and the pager, and an allowlist is the only safe shape here
  (`sandbox.ALLOWED_GIT_CONFIG_OVERRIDES` says why), so a config **write** may set only
  `SAFE_CONFIG_KEYS`, never to a `!` value. Reads are not limited.
* **Subcommands that run one by design:** `submodule foreach`, `bisect run`,
  `filter-branch`, `difftool`, `mergetool`, and the servers and browsers.
* **Options that name a program:** `rebase --exec`, `--upload-pack` and
  `--receive-pack`, `grep --open-files-in-pager`, a template directory, a config
  passed to a clone, and `--exec-path`.

This is a screen over the argument list, like `runtime.guard` over a body, and it says
what it cannot see. A git command that runs a program not listed here is not refused,
and the harness sandbox has no filesystem boundary of its own (issue #10). It is the
tool's own screen: a replayed body is shell already, and `runtime.guard` screens it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..sandbox import git_invocation

SAFE_CONFIG_KEYS = re.compile(
    r"(?:"
    r"branch\..+\.(?:remote|merge|rebase|pushremote|description)"
    r"|remote\..+\.(?:url|pushurl|fetch|push|tagopt|prune|mirror)"
    r"|submodule\..+\.(?:url|active|branch|update|ignore|shallow|fetchrecursesubmodules)"
    r"|user\.(?:name|email)"
    r"|pull\.(?:rebase|ff)"
    r"|merge\.(?:ff|conflictstyle|autostash)"
    r"|rebase\.(?:autostash|autosquash|updaterefs)"
    r"|push\.(?:default|autosetupremote)"
    r"|fetch\.(?:prune|prunetags)"
    r"|init\.defaultbranch"
    r"|rerere\.(?:enabled|autoupdate)"
    r"|advice\.[a-z0-9]+"
    r"|color\.[a-z0-9.-]+"
    r"|core\.(?:autocrlf|eol|filemode|ignorecase|quotepath|safecrlf)"
    r")",
    re.IGNORECASE,
)
"""The config keys a repository chore sets, none of which can name a command.

Matched against the whole key, case-insensitively, as git compares names. A key that
is not here is refused even when it is harmless: the keys that run a command are too
many to list, which is why this is an allowlist."""

_COMMAND_SUBCOMMANDS: dict[str, str] = {
    "difftool": "runs an external diff program",
    "mergetool": "runs an external merge program",
    "filter-branch": "runs its filters as shell commands",
    "instaweb": "starts a web server",
    "web--browse": "starts a browser",
    "daemon": "starts a server",
    "send-email": "sends mail",
}

_COMMAND_ACTIONS: dict[tuple[str, str], str] = {
    ("submodule", "foreach"): "runs a shell command in every submodule",
    ("bisect", "run"): "runs a command at every step",
}

_COMMAND_OPTIONS: dict[str, tuple[str, ...]] = {
    "rebase": ("--exec", "-x"),
    "fetch": ("--upload-pack",),
    "pull": ("--upload-pack",),
    "ls-remote": ("--upload-pack", "-u"),
    "fetch-pack": ("--upload-pack", "--exec"),
    "clone": ("--upload-pack", "-u", "--config", "-c", "--template"),
    "init": ("--template",),
    "push": ("--receive-pack", "--exec"),
    "send-pack": ("--receive-pack", "--exec"),
    "archive": ("--exec",),
    "grep": ("--open-files-in-pager", "-O"),
}
"""Per subcommand, the options whose value is a program git runs, or a source of
config or hooks a new repository starts from."""

_CONFIG_READ_FLAGS = frozenset(
    {
        "--get",
        "--get-all",
        "--get-regexp",
        "--get-urlmatch",
        "--get-color",
        "--get-colorbool",
        "-l",
        "--list",
    }
)
_CONFIG_REMOVE_FLAGS = frozenset({"--unset", "--unset-all", "--remove-section"})
_CONFIG_OPTIONS_WITH_VALUE = frozenset(
    {"-f", "--file", "--blob", "--type", "-t", "--default", "--comment", "--value"}
)


def command_running_reason(argv: Sequence[str]) -> str | None:
    """Why git would run a command for this tokenised `git ...` line, or `None`."""
    global_options, subcommand, args = git_invocation(argv)
    for option in global_options:
        if option.startswith("--exec-path="):
            return "'--exec-path' makes git look for its subcommands in another directory"
    if subcommand is None:
        return None
    if subcommand in _COMMAND_SUBCOMMANDS:
        return f"'git {subcommand}' {_COMMAND_SUBCOMMANDS[subcommand]}"
    action = next((arg for arg in args if not arg.startswith("-")), None)
    if action is not None and (subcommand, action) in _COMMAND_ACTIONS:
        return f"'git {subcommand} {action}' {_COMMAND_ACTIONS[(subcommand, action)]}"
    for option in _COMMAND_OPTIONS.get(subcommand, ()):
        if any(_names_option(arg, option) for arg in args):
            return f"'git {subcommand} {option}' names a program or config for git to use"
    if subcommand == "config":
        return _config_reason(args)
    return None


def _names_option(arg: str, option: str) -> bool:
    """Whether `arg` is `option`, with its value attached or not.

    A short option may sit in a cluster (`-ix` is `-i -x`), so its letter anywhere in a
    single-dash token counts. That can refuse a cluster that only looked like one,
    which costs the agent a retry, not a command run.
    """
    if option.startswith("--"):
        return arg == option or arg.startswith(f"{option}=")
    return arg.startswith("-") and not arg.startswith("--") and option[1] in arg[1:]


def _config_reason(args: list[str]) -> str | None:
    """Why this `git config` would leave config that runs a command, or `None`.

    Reads and removals cannot add one. An editor is a command. Renaming a section can
    move entries under a name git runs (`--rename-section x alias`). A write must set a
    `SAFE_CONFIG_KEYS` key, never to a `!` value.
    """
    flags: list[str] = []
    positionals: list[str] = []
    values: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("-"):
            name, attached, value = arg.partition("=")
            flags.append(name)
            if not attached and arg in _CONFIG_OPTIONS_WITH_VALUE and index + 1 < len(args):
                index += 1
                value = args[index]
            if name == "--value":
                values.append(value)
        else:
            positionals.append(arg)
        index += 1
    action = positionals[0] if positionals else None
    if {"-e", "--edit"} & set(flags) or action == "edit":
        return "'git config --edit' opens an editor, which is a command"
    if "--rename-section" in flags or action == "rename-section":
        return "renaming a config section can move entries under a name git runs"
    if _CONFIG_READ_FLAGS & set(flags) or action in {"get", "list"}:
        return None
    if _CONFIG_REMOVE_FLAGS & set(flags) or action in {"unset", "remove-section"}:
        return None
    if action == "set":
        positionals = positionals[1:]
    if not positionals or (len(positionals) < 2 and not values):
        return None  # a key alone reads it
    key = positionals[0]
    values = [*positionals[1:], *values]
    if not SAFE_CONFIG_KEYS.fullmatch(key):
        return (
            f"'git config {key}' may name a command for git to run; this tool sets only "
            "branch, remote, submodule, user and a few behaviour keys"
        )
    if any(value.startswith("!") for value in values):
        return "a config value starting with '!' is a shell command"
    return None
