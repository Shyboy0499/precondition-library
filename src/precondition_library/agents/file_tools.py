"""The agent's file reader and writer, confined to the repository's working tree.

Arm 1 must have "the same tool surface the compiled programs get" (`react`), and a
compiled body is shell: it can rebuild a file with `git show`, `sed` and a redirect.
The agent had only `run_git`, so a chore that needs a file's content written -- a
conflicted lock file rebuilt from both sides -- had no honest route. In the fourth live
smoke run it failed every lockfile solve but one. The one success used `git notes add -m`
to make a blob and `update-index` to stage it, and another solve set a `!sed` alias,
which `command_screen` now refuses. These two tools are the honest route.

**What confines them.** A path is relative to `env.work` and is refused when it:

* is absolute, or climbs with `..`;
* names a `.git` component. Git's own directory holds config and hooks, which are how a
  file becomes a command;
* passes through, or ends at, a symbolic link, so a link inside the tree cannot point a
  write outside it;
* resolves outside the working tree anyway.

A write creates any missing directories, replaces the file's whole content, and creates
new files without the executable bit. Content is text, capped at `MAX_FILE_BYTES`. Both
tools return their result as text, and a refusal is a result the agent can read, as
`run_git`'s are.

On an existing checkout the agent solves a disposable copy (`learn`), and `env.work` is
that copy, so these tools never touch the user's own working tree.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_FILE_BYTES = 64 * 1024
"""The largest file either tool reads or writes. A maintenance chore's files here are a
few KiB, and every tool result is re-sent on each later turn."""

READ_FILE = "read_file"
WRITE_FILE = "write_file"


def file_tools() -> list[dict]:
    """The two tools' schemas, in the function-calling shape `react.available_tools` uses."""
    path = {
        "type": "string",
        "description": "A path relative to the repository root, e.g. 'deps.lock'.",
    }
    return [
        {
            "type": "function",
            "function": {
                "name": READ_FILE,
                "description": (
                    "Read a text file in the repository's working tree, as it is on disk now "
                    "(including any conflict markers). Files inside .git cannot be read."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"path": path},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": WRITE_FILE,
                "description": (
                    "Replace a text file's whole content in the repository's working tree, "
                    "creating it if needed. Files inside .git cannot be written. Stage and "
                    "commit with run_git afterwards."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": path,
                        "content": {
                            "type": "string",
                            "description": "The file's complete new content.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
    ]


def read_file(path: str, work: Path) -> tuple[str, bool]:
    """Read `path` under `work`; return (result text, ok)."""
    target = _confined(path, work)
    if isinstance(target, str):
        return _refused(target), False
    if not target.is_file():
        return f"no such file: {path}", False
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        return _refused(f"{path} is {size} bytes; the limit is {MAX_FILE_BYTES}"), False
    return target.read_bytes().decode("utf-8", errors="replace"), True


def write_file(path: str, content: str, work: Path) -> tuple[str, bool]:
    """Replace `path` under `work` with `content`; return (result text, ok)."""
    target = _confined(path, work)
    if isinstance(target, str):
        return _refused(target), False
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        return _refused(f"content is {len(data)} bytes; the limit is {MAX_FILE_BYTES}"), False
    if target.is_dir():
        return _refused(f"{path} is a directory"), False
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    return f"wrote {path} ({len(data)} bytes)", True


def _confined(path: str, work: Path) -> Path | str:
    """The file `path` names under `work`, or why it may not be touched."""
    if not path or "\0" in path:
        return "a path is required"
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return f"{path!r} is absolute; give a path relative to the repository root"
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if ".." in parts:
        return f"{path!r} climbs out with '..'"
    if any(part.lower() == ".git" for part in parts):
        return f"{path!r} is inside .git, which holds git's config and hooks"
    root = work.resolve()
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return f"{path!r} goes through a symbolic link"
    if not current.resolve().is_relative_to(root):
        return f"{path!r} is outside the working tree"
    return current


def _refused(reason: str) -> str:
    return f"refused: {reason}"
