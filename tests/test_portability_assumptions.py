"""The platform assumptions the suite rests on, pinned as tests (#87).

Three of the defects in #87 pass on Linux and fail on Windows, and one of them
stops the suite from being *collected* at all outside a git checkout. Every
assertion here guards a way this repository could pass on one platform and
silently do nothing on another -- and "silently do nothing" is the failure class
the library exists to measure, so it should not be reachable inside it.

What is pinned is deliberately the *code property* each defect rests on, not the
Windows behaviour, because no CI job here runs Windows yet:

- the interpreter `SHELL` actually resolves to and can execute;
- the line endings a gold body arrives with;
- the handler that removes a sandbox, and its refusal to swallow a failure;
- the degradation a non-git checkout takes instead of an import error.

Some of these import underscore-prefixed helpers. That is on purpose: POSIX
deletion succeeds against a read-only *file* (only the containing directory has
to be writable), so the Windows path through `_clear_readonly` cannot be reached
end-to-end on this machine. Asserting the handler's own contract is the part that
is falsifiable here, and it is the part that would silently regress.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import conftest
import pytest
import yaml

from precondition_library.runtime.probes import SHELL
from precondition_library.sandbox import (
    _clear_readonly,
    _clear_readonly_quiet,
    _force_writable,
)

GOLD_DIR = Path(__file__).resolve().parents[1] / "bench" / "gold"


def test_force_writable_adds_the_write_bit_without_dropping_the_others(tmp_path) -> None:
    """The removal handler must *add* permission, not replace the mode.

    `os.chmod(path, stat.S_IWRITE)` is the recipe usually quoted for clearing
    git's read-only attribute, and it is only correct on Windows. On POSIX it sets
    the mode to owner-write alone, so a directory that tripped the handler would
    lose its execute bit and stop being traversable -- trading one platform's
    failure for the other's. OR-ing the bit in is what both platforms want, and
    this fails if that is ever simplified back to the quoted form.
    """
    target = tmp_path / "loose-object"
    target.write_text("blob", encoding="utf-8")
    os.chmod(target, 0o444)

    _force_writable(str(target))

    mode = os.lstat(target).st_mode
    assert mode & stat.S_IWUSR, "the write bit was not added"
    assert mode & stat.S_IRUSR, "the read bit was dropped"
    assert mode & stat.S_IRGRP, "the group read bit was dropped"


def test_clear_readonly_clears_the_write_protection_before_reissuing_the_call(tmp_path) -> None:
    """It is a `onexc` handler: clear the write protection, then re-issue the call.

    `rmtree` has already made the attempt that failed, so the handler's job is the
    retry -- exactly one call is expected. Asserting the mode *as the retry sees
    it* is the point: a retry that ran before the chmod would repeat the identical
    failure on Windows and look like a fix.
    """
    target = tmp_path / "object"
    target.write_text("blob", encoding="utf-8")
    os.chmod(target, 0o444)
    modes: list[int] = []

    def record_mode_at_call_time(path: str) -> None:
        modes.append(os.lstat(path).st_mode)

    _clear_readonly(record_mode_at_call_time, str(target), PermissionError("read-only"))

    assert len(modes) == 1, "the handler must re-issue the failed call exactly once"
    assert modes[0] & stat.S_IWUSR, "the retry ran before the write bit was cleared"


def test_clear_readonly_reraises_what_the_retry_cannot_fix(tmp_path) -> None:
    """`create()` must stay loud: a real failure belongs at the call site that caused it."""

    def always_fails(path: str) -> None:
        raise PermissionError("still denied")

    with pytest.raises(PermissionError, match="still denied"):
        _clear_readonly(always_fails, str(tmp_path), PermissionError("denied"))


def test_clear_readonly_quiet_records_a_failure_instead_of_swallowing_it(tmp_path, recwarn) -> None:
    """`destroy()` must not discard the failure it cannot fix.

    `ignore_errors=True` is the silent half of #87's D1: the deletion fails, the
    exception vanishes, `.sandboxes/` keeps residue, and the crash lands later in
    whichever unrelated test next calls `create()` -- naming neither the residue
    nor the call that left it. Warning is the record.
    """

    def always_fails(path: str) -> None:
        raise PermissionError("still denied")

    _clear_readonly_quiet(always_fails, str(tmp_path), PermissionError("denied"))

    assert [w for w in recwarn if issubclass(w.category, RuntimeWarning)], (
        "the failure was swallowed; residue would surface later in an unrelated test"
    )


def test_clear_readonly_quiet_stays_silent_when_the_path_is_already_gone(recwarn) -> None:
    """`destroy()` is documented idempotent, so an absent root must not warn."""
    missing = Path("/nonexistent-precondition-library/root")

    _clear_readonly_quiet(
        os.unlink, str(missing), FileNotFoundError(2, "No such file or directory")
    )

    assert not recwarn, "an already-destroyed sandbox warned"


def test_shell_actually_runs_a_command_under_bash() -> None:
    """`SHELL` must resolve to an interpreter that executes, not one that exits 1.

    On Windows a bare `bash` is the WSL launcher: with no distribution installed
    it exits non-zero *without running the command*, so every precondition
    evaluates false and every body silently does nothing while the run still looks
    complete. `$BASH_VERSION` is the non-POSIX part of the assertion -- `sh` would
    run the command and leave it empty, and the module's whole reason for naming
    bash rather than `/bin/sh` is that the gold probes need bash extensions.
    """
    completed = subprocess.run(
        [*SHELL, 'printf "%s" "$BASH_VERSION"'],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, f"{SHELL[0]} did not run a command: {completed.stderr!r}"
    assert completed.stdout, f"{SHELL[0]} ran, but not under bash ($BASH_VERSION was empty)"


def test_shell_supports_the_process_substitution_the_gold_probes_need() -> None:
    """The extension the module docstring names as the reason for `bash -c`."""
    completed = subprocess.run(
        [*SHELL, "comm -12 <(printf 'a\\nb\\n') <(printf 'b\\nc\\n')"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, f"process substitution failed: {completed.stderr!r}"
    assert completed.stdout.strip() == "b"


def test_gold_bodies_never_arrive_with_carriage_returns() -> None:
    """A `\\r` in a body is invisible and can disable the entire body.

    `bench/gold/*.yaml` bodies are handed to `bash -c`. Under a CRLF checkout the
    trailing `\\r` can make a whole body ineffective while the command still exits
    0 -- indistinguishable from a real mis-fire in the ledger, which is the
    measurement this repository exists to make. `.gitattributes` pins `eol=lf` so
    a Windows clone cannot produce that; this asserts the artifact, so removing
    the setting fails here rather than at measurement time.
    """
    bodies = [
        program["body"]
        for path in sorted(GOLD_DIR.glob("*.yaml"))
        for program in yaml.safe_load(path.read_text(encoding="utf-8"))["programs"]
    ]

    assert bodies, "no gold bodies loaded; the glob or the schema changed, so this pins nothing"
    offenders = [body for body in bodies if "\r" in body]
    assert not offenders, f"{len(offenders)} gold bodies contain a carriage return"


def test_git_status_returns_none_outside_a_git_repository(tmp_path, monkeypatch) -> None:
    """#87 D6: a checkout with no `.git` must degrade, not stop collection.

    A GitHub *Download ZIP* snapshot has no `.git`, so `git status` exits 128.
    Raised at import time that became "the suite cannot be collected at all"
    (exit 4, nothing run), and the error named neither git nor the missing
    `.git`. `None` is the degradation; the `repository_unchanged` fixture turns it
    into a skip.
    """
    # Without this, git would walk up from `tmp_path` and could find a repository
    # above it on some machines, making the assertion depend on the temp layout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setattr(conftest, "ROOT", tmp_path)

    assert conftest.git_status_porcelain() is None
