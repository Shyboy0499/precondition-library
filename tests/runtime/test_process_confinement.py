"""Bodies and probes are confined: the whole process group dies on timeout (issue #10).

`subprocess.run(timeout=...)` killed only the shell it started, so work the shell had put
in the background outlived the timeout meant to stop it. `runtime.confine.run_confined`
starts each command in its own group and kills the group. The survivor is observed by
its effect: a background subshell that writes a marker file after the timeout has
passed. Each property has a control that runs the same command the old way and sees the
marker appear, so the test is shown able to fail.

The file-size limit is POSIX-only (`RLIMIT_FSIZE`); Windows job objects are not
implemented, which #10 still lists.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_episode_runner import DISCARD_SEED, _discard_program

from precondition_library.program import Predicate
from precondition_library.runtime import confine
from precondition_library.runtime.probes import SHELL, bindings, evaluate_predicate
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import git_env

_LATE = "late-marker.txt"
_OUTLIVES_TIMEOUT = f"(sleep 3; echo alive > {_LATE}) & sleep 30"
"""Backgrounds a writer that fires after the 1s timeout, then blocks past it."""


def _settle() -> None:
    """Wait past the moment a surviving writer would have written its marker."""
    time.sleep(4)


def test_the_old_way_leaves_a_background_writer_running(make_sandbox) -> None:
    """Control: `subprocess.run(timeout=...)` kills the shell and not its children."""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [*SHELL, _OUTLIVES_TIMEOUT],
            cwd=box.work,
            env=git_env(home=box.root),
            capture_output=True,
            timeout=1,
        )
    _settle()
    assert (box.work / _LATE).exists(), (
        "the control must show a survivor, or the test proves nothing"
    )


def test_a_timed_out_body_takes_its_background_work_with_it(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    result = replay(_discard_program(body=_OUTLIVES_TIMEOUT), box, timeout_s=1)
    assert result.timed_out is True
    _settle()
    assert not (box.work / _LATE).exists(), "a background writer outlived the body's timeout"


def test_a_timed_out_probe_takes_its_background_work_with_it(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    probe = Predicate(name="slow", description="backgrounds a writer", probe=_OUTLIVES_TIMEOUT)
    result = evaluate_predicate(probe, box, bindings(box), timeout_s=1)
    assert result.ok is False and "timed out" in result.observed
    _settle()
    assert not (box.work / _LATE).exists(), "a background writer outlived the probe's timeout"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="RLIMIT_FSIZE is POSIX-only; Windows job objects are not implemented (issue #10)",
)
def test_a_write_past_the_file_size_limit_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(confine, "FILE_SIZE_LIMIT_BYTES", 1024 * 1024)
    result = confine.run_confined(
        [*SHELL, "head -c 2097152 /dev/zero > big.bin"],
        cwd=tmp_path,
        env=git_env(home=tmp_path),
        timeout_s=10,
    )
    assert result.returncode != 0
    assert (tmp_path / "big.bin").stat().st_size <= 1024 * 1024
