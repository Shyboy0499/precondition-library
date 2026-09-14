"""The boundary between generated code and the machine.

Compiled bodies are authored by a model that has been reading untrusted
repository content, and they execute unattended on repeat. Two consequences
shape this module:

* Screening is deny-by-default over *effects*, not intent. We cannot know what
  the model meant; we can refuse to hand it a filesystem root, a force-push to
  a shared remote, or a network fetch that exfiltrates repository contents.
* What the guard cannot make safe, it makes recoverable: destructive-looking
  programs are still permitted to run inside a disposable sandbox, because that
  is what the sandbox is for -- the guard's job is to guarantee the sandbox is
  the only thing at risk.

A refused program is recorded, not silently skipped. The refusal rate is part of
the result, and a high one means the compile prompt is producing dangerous code
rather than that the guard is being annoying.

What the guard cannot see
-------------------------
This is a textual screen over one shell body, not an interpreter and not a
sandbox boundary. The design spec says as much (a seatbelt, not a sandbox
boundary); this section says precisely where the seatbelt has no purchase:

* Values computed at run time. ``p=/etc; rm -rf "$p"``, a path reached through a
  variable, or a URL assembled from pieces are invisible here. A command named
  through a variable is not recognised at all.
* Anything behind an interpreter or an encoding: ``eval``, ``bash -c``,
  ``python -c``, ``perl``, a base64 blob. Only the obvious network-module
  heuristics are attempted for those, and they are heuristics.
* Remotes by resolution. A force-push to a *named* remote is refused even when
  the name is the sandbox's own ``upstream``, because telling a sandbox remote
  from a shared one means running git; only a path under ``env_root`` is
  accepted as recognisably local.
* Symlinks. ``_within_env`` normalises the path text, it does not follow links,
  so a symlink inside ``env_root`` can still point outside it.
* Writes through programs not in the writer set below, and reads that do not
  name a credential-shaped path or an environment variable.

Every rule here names an effect it can read off the text. Effects it cannot
read are not refused, which is why the sandbox -- discarded afterwards -- is
what contains a body, and the guard is only a first pass over it.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "allow"
    REFUSE = "refuse"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str = ""


# --- effect recognisers -----------------------------------------------------

_URL_SCHEME = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s'\"`|;&)<>]*")
_SCP_LIKE = re.compile(r"\bgit@[A-Za-z0-9._-]+:")
_NETWORK_TOOLS = frozenset(
    {
        "curl",
        "wget",
        "nc",
        "ncat",
        "netcat",
        "ssh",
        "scp",
        "sftp",
        "telnet",
        "ftp",
        "socat",
        "rsync",
        "dig",
        "nslookup",
        "host",
        "ping",
        "traceroute",
        "smbclient",
        "rclone",
        "aws",
        "gcloud",
        "az",
        "gh",
    }
)
_INTERPRETERS = frozenset({"python", "python3", "perl", "ruby", "node", "php"})
_NETWORK_MODULES = re.compile(
    r"\b(?:socket|urllib|requests|httpx|http\.client|net/http|open-uri|Net::HTTP)\b"
)

_CREDENTIAL = re.compile(
    r"\.ssh(?:/|\b)"
    r"|(?<![.\w])id_(?:rsa|dsa|ecdsa|ed25519)\b"
    r"|\.git-credentials\b"
    r"|(?<![.\w])\.netrc\b"
    r"|\.aws(?:/|\b)"
    r"|\bcredentials\.json\b"
    r"|\.kube(?:/|\b)"
    r"|/etc/(?:passwd|shadow)\b"
    r"|(?<![.\w])\.env(?![\w.])"
    r"|\b[A-Za-z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD)[A-Za-z0-9_]*\b"
)

_ENV_VAR = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*|\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_ENV_DUMPERS = frozenset({"env", "printenv"})
_ENV_READ_EXPR = re.compile(r"\b(?:os\.environ|process\.env|getenv\s*\()")

_CONFIG_READ_FLAGS = frozenset({"--get", "--get-all", "--get-regexp", "--list", "-l"})

_WRITE_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "mv",
        "cp",
        "dd",
        "truncate",
        "shred",
        "chmod",
        "chown",
        "chgrp",
        "ln",
        "mkdir",
        "touch",
        "tee",
        "install",
        "unlink",
        "mkfifo",
        "mknod",
    }
)
_REDIRECT = re.compile(r"^(?:&>|\d*>>?)(.+)$")
_REDIRECT_TOKENS = frozenset({">", ">>", ">|", "&>", "<>"})
_NON_WRITE_TARGETS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"})
_SEGMENT_SEPARATORS = re.compile(r"&&|\|\||[;\n|]|\$\(|`")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _commands(body: str) -> list[list[str]]:
    """Split a shell body into commands, as token lists.

    Best-effort, not a parser: separators split the text, `shlex` tokenises each
    segment, and leading `VAR=value` assignments are dropped so the command name
    is the first token. A segment that does not tokenise is skipped rather than
    raising -- the screen must not crash on the bodies it is there to inspect.
    """
    commands: list[list[str]] = []
    for raw in _SEGMENT_SEPARATORS.split(body):
        try:
            tokens = shlex.split(raw, posix=True)
        except ValueError:
            continue
        while tokens and _ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        if tokens:
            commands.append(tokens)
    return commands


def _looks_like_path(token: str) -> bool:
    return token.startswith(("/", "~", ".")) or "/" in token


def _within_env(path: str, env_root: str) -> bool:
    """Whether `path`, resolved relative to `env_root`, stays inside it.

    Textual normalisation only: symlinks are not followed (see the module
    docstring), and a path that does not exist is still comparable.
    """
    root = os.path.normpath(os.path.abspath(env_root))
    absolute = path if os.path.isabs(path) else os.path.join(root, path)
    target = os.path.normpath(os.path.abspath(absolute))
    return target == root or target.startswith(root + os.sep)


def _escapes_env(target: str, env_root: str) -> bool:
    target = target.strip("'\"")
    if not target or target.startswith("&"):
        return False
    if target.startswith("~"):
        # `~` is the operator's home, outside any sandbox, even though it has no
        # slash for `_looks_like_path` to see.
        return True
    if not _looks_like_path(target):
        return False
    return not _within_env(target, env_root)


def _network_effect(body: str) -> str | None:
    url = _URL_SCHEME.search(body) or _SCP_LIKE.search(body)
    if url:
        return f"target {url.group(0)!r}"
    for tokens in _commands(body):
        name = os.path.basename(tokens[0])
        if name in _NETWORK_TOOLS:
            return f"command {name!r}"
        if name in _INTERPRETERS and _NETWORK_MODULES.search(" ".join(tokens[1:])):
            return f"{name} using a network module"
    return None


def _credential_effect(body: str) -> str | None:
    match = _CREDENTIAL.search(body)
    return match.group(0) if match else None


def _env_read_effect(body: str) -> str | None:
    match = _ENV_VAR.search(body) or _ENV_READ_EXPR.search(body)
    if match:
        return match.group(0)
    for tokens in _commands(body):
        if os.path.basename(tokens[0]) in _ENV_DUMPERS:
            return f"command {os.path.basename(tokens[0])!r}"
    return None


def _global_config_write_effect(body: str) -> str | None:
    for tokens in _commands(body):
        if os.path.basename(tokens[0]) != "git" or "config" not in tokens:
            continue
        if "--global" not in tokens:
            continue
        rest = tokens[tokens.index("--global") + 1 :]
        if rest and rest[0] in _CONFIG_READ_FLAGS:
            continue
        return "git config --global write"
    return None


def _force_push_effect(body: str, env_root: str) -> str | None:
    for tokens in _commands(body):
        if os.path.basename(tokens[0]) != "git" or "push" not in tokens:
            continue
        args = tokens[tokens.index("push") + 1 :]
        forced = any(
            arg in {"--force", "-f"}
            or arg.startswith("--force-with-lease")
            or arg.startswith("--force-if-includes")
            or (arg.startswith("+") and ":" in arg)
            for arg in args
        )
        if not forced:
            continue
        positionals = [arg for arg in args if not arg.startswith(("-", "+"))]
        remote = positionals[0] if positionals else None
        recognised = (
            remote is not None and _looks_like_path(remote) and _within_env(remote, env_root)
        )
        if not recognised:
            return f"force-push to remote {remote or '<default>'}"
    return None


def _outside_write_effect(body: str, env_root: str) -> str | None:
    for tokens in _commands(body):
        name = os.path.basename(tokens[0])
        targets: list[str] = []
        for index, token in enumerate(tokens):
            match = _REDIRECT.match(token)
            if match:
                targets.append(match.group(1))
            elif token in _REDIRECT_TOKENS and index + 1 < len(tokens):
                targets.append(tokens[index + 1])
        if name in _WRITE_COMMANDS:
            targets.extend(tokens[1:])
        elif name == "sed" and any(t == "-i" or t.startswith("-i") for t in tokens[1:]):
            targets.extend(tokens[1:])
        elif name == "find" and any(t in {"-delete", "-exec", "-execdir"} for t in tokens[1:]):
            targets.extend(tokens[1:])
        elif name == "git" and "config" in tokens and "--file" in tokens:
            index = tokens.index("--file")
            if index + 1 < len(tokens):
                targets.append(tokens[index + 1])
        for target in targets:
            target = target.strip("'\"")
            if target in _NON_WRITE_TARGETS:
                continue
            if _escapes_env(target, env_root):
                return f"{target!r} is outside env_root {env_root!r}"
    return None


def screen(body: str, *, env_root: str) -> Decision:
    """Inspect a program body before execution, refusing by effect.

    Refuses: writes outside `env_root`, outbound network calls, credential and
    environment-variable reads, `git config --global` writes, and force-pushes to
    a remote not recognisable as the sandbox. Everything else runs inside the
    sandbox -- including destructive operations there, which are permitted on
    purpose because the sandbox is disposable and destroying it is the contained
    outcome.

    Each refusal reason names the effect it refused. A refusal is data for the
    caller, not a skip: the refusal rate is a finding about the compile step.
    What the screen cannot see is documented in the module docstring; it is not
    a sandbox boundary.
    """
    checks = (
        ("outbound network call", _network_effect(body)),
        ("credential read", _credential_effect(body)),
        ("environment-variable read", _env_read_effect(body)),
        ("git config --global write", _global_config_write_effect(body)),
        ("force-push outside the sandbox", _force_push_effect(body, env_root)),
        ("write outside env_root", _outside_write_effect(body, env_root)),
    )
    for effect, detail in checks:
        if detail is not None:
            return Decision(Verdict.REFUSE, f"refused {effect}: {detail}")
    return Decision(Verdict.ALLOW)


def prepare_dry_run(program, env) -> Decision:
    """Report what a program would do, without letting it do it.

    **Nothing consumes this yet.** It is left as a stub deliberately: no caller
    needs a dry run, and implementing a feature with no consumer would be work
    with no evidence behind it. The admission path (issue #4) is its first
    prospective consumer. Git has no general dry-run, so it is implemented by
    running the body against a copy of the environment and diffing -- the copy
    is discarded.
    """
    raise NotImplementedError(
        "no caller needs a dry run yet; the admission path (issue #4) is its "
        "first prospective consumer and will implement it"
    )
