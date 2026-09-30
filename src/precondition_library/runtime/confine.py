"""Run model-authored shell under the confinement a process can give itself (issue #10).

Bodies and probes are model-authored text executed unattended, so the runtime is the only
barrier between them and the host. #10 asks that replay run "as an unprivileged user with
no network, ulimits, a disk quota, and the process group killed on timeout". This module
implements the parts that need no privilege and states the rest:

* **The whole process group dies on timeout.** `subprocess.run(timeout=...)` killed only
  the shell it started; anything the shell had put in the background -- a `sleep 1000 &`,
  a stuck `git` child -- outlived the timeout and kept running in the sandbox, or after
  it. Each command now starts its own group (a new session on POSIX, a new process group
  on Windows) and the group is killed on expiry: `killpg` on POSIX, `taskkill /T /F` on
  Windows.
* **Resource limits (POSIX only).** A per-file size cap (`FILE_SIZE_LIMIT_BYTES`) so a
  runaway write cannot fill the disk through one file, and core dumps off. Windows has no
  `setrlimit`; job objects would be its equivalent and are not implemented.

**Not done here, because a process cannot do it to itself without privilege:** a separate
unprivileged user, network isolation, and a real disk quota. Those need root, user
namespaces or a container, and remain open in #10. A process that deliberately leaves its
group -- `setsid` inside the body -- also escapes the group kill; the guard screens the
text, but that is screening, not a boundary.

Imports only the standard library, so `runtime` still cannot reach the provider.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

FILE_SIZE_LIMIT_BYTES = 256 * 1024 * 1024
"""The largest file a confined command may write (POSIX `RLIMIT_FSIZE`).

256 MiB is far above anything a git maintenance chore on these sandboxes writes -- the
largest file an injector creates is a few KiB -- and far below what fills a CI runner's
disk. A write past it fails with `SIGXFSZ`/`EFBIG`, which the caller sees as a failed
command."""

_IS_WINDOWS = sys.platform == "win32"

_NEW_PROCESS_GROUP: int = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
"""Windows' flag for a new process group; the attribute exists only there, and 0 is a no-op."""


@dataclass(frozen=True)
class Confined:
    """How a confined command ended."""

    returncode: int | None
    """The exit status, or `None` when the command was killed on timeout."""
    stdout: str
    stderr: str
    timed_out: bool


def _limits() -> None:  # pragma: no cover - runs in the child, between fork and exec
    import resource

    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _kill_group(process: subprocess.Popen[str]) -> None:
    """Kill `process` and everything it started, however it was left."""
    if _IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.kill()


def run_confined(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> Confined:
    """Run `argv` in its own process group, under the POSIX limits, killed whole on timeout.

    Output is decoded as UTF-8 with replacement, as both callers did before, so an
    undecodable byte cannot turn `stdout` into `None`.
    """
    preexec: Callable[[], None] | None = None if _IS_WINDOWS else _limits
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=not _IS_WINDOWS,
        creationflags=_NEW_PROCESS_GROUP,
        preexec_fn=preexec,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        stdout, stderr = process.communicate()
        return Confined(returncode=None, stdout=stdout or "", stderr=stderr or "", timed_out=True)
    return Confined(returncode=process.returncode, stdout=stdout, stderr=stderr, timed_out=False)
