"""A confined command runs with no network where the host allows it (issue #10).

#10 asks that replay run "with no network". `runtime.confine` runs each body and
probe inside a fresh, empty network namespace (`unshare --net`) when the host can
create one, which is a kernel boundary rather than the guard's textual screen. The
privilege to create a namespace may be withheld (a non-root CI runner, a locked-down
container), and the owner's choice is to run anyway and record whether isolation was
applied, not to refuse -- so these tests pin both the applied path (where available)
and the recorded-fallback path (everywhere, deterministically).

Run against real processes and real sandboxes: whether egress is blocked is a
property of the kernel, not of a mock.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from conftest import gold_program

from precondition_library.runtime import confine
from precondition_library.runtime.confine import network_isolation_available, run_confined
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import git_env

# Exits 7 if it cannot reach the network, 0 if it can. Run through `run_confined`
# directly (not a body), because the guard refuses a socket-using body before it
# could run -- the point here is the layer beneath the guard.
_EGRESS = (
    "import socket, sys\n"
    "try:\n"
    "    socket.create_connection(('1.1.1.1', 443), timeout=3).close()\n"
    "    sys.exit(0)\n"
    "except OSError:\n"
    "    sys.exit(7)\n"
)


def test_the_probe_is_a_cached_bool() -> None:
    first = network_isolation_available()
    assert isinstance(first, bool)
    assert network_isolation_available() is first  # cached, so stable within a run


def test_egress_is_blocked_when_isolation_is_available() -> None:
    if not network_isolation_available():
        pytest.skip(
            "host cannot create a network namespace (issue #10); fallback path tested below"
        )
    work = Path(tempfile.mkdtemp(prefix="netns-"))
    result = run_confined([sys.executable, "-c", _EGRESS], cwd=work, env=git_env(), timeout_s=15)
    assert result.network_isolated is True
    assert result.returncode == 7, "an empty network namespace must block the connection"


def test_fallback_runs_the_command_and_records_not_isolated(monkeypatch) -> None:
    """Where isolation is unavailable the command still runs, recorded as not isolated."""
    monkeypatch.setattr(confine, "network_isolation_available", lambda: False)
    work = Path(tempfile.mkdtemp(prefix="netns-"))
    result = run_confined(
        [sys.executable, "-c", "print('ran')"], cwd=work, env=git_env(), timeout_s=15
    )
    assert result.network_isolated is False
    assert result.returncode == 0 and "ran" in result.stdout


def test_replay_records_whether_the_body_ran_isolated(make_sandbox) -> None:
    box = make_sandbox(1, ["diverged"])
    result = replay(gold_program("discard"), box)
    assert result.network_isolated == network_isolation_available()
    if network_isolation_available():
        # Local-path git (the sandbox's only "remote") still works under isolation.
        assert result.ok, result.reason


def test_a_refused_body_is_not_recorded_as_isolated(make_sandbox) -> None:
    """Nothing ran, so nothing was isolated, whatever the host can do."""
    box = make_sandbox(1, ["diverged"])
    program = gold_program("discard").model_copy(
        update={"steps": None, "body": "curl -s http://exfil.invalid/x"}
    )
    result = replay(program, box)
    assert result.refused is True
    assert result.network_isolated is False
