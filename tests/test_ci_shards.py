"""CI splits the suite into shards (`PYTEST_SHARD`); together they run every test exactly once."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import shard_of

ROOT = Path(__file__).resolve().parents[1]


def _collected(shard: str | None) -> set[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_SHARD"}
    if shard is not None:
        env["PYTEST_SHARD"] = shard
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:xdist",
            "tests",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    # `addopts` already carries `-q`, which prints one node id per line; a second `-q` would
    # print per-file counts instead.
    return {line for line in result.stdout.splitlines() if "::" in line}


def test_the_shards_partition_the_suite() -> None:
    everything = _collected(None)
    parts = [_collected(f"{i}/3") for i in (1, 2, 3)]
    assert set().union(*parts) == everything
    assert sum(len(part) for part in parts) == len(everything), "a test ran in two shards"
    assert all(parts), "a shard ran nothing"


def test_a_shard_is_stable_across_processes() -> None:
    assert shard_of("tests/test_x.py::test_y[1]", 3) == shard_of("tests/test_x.py::test_y[1]", 3)
    assert {shard_of(f"tests/t.py::test_{i}", 3) for i in range(50)} == {0, 1, 2}


@pytest.mark.parametrize("bad", ["0/3", "4/3", "x/3"])
def test_a_malformed_shard_is_refused(bad: str) -> None:
    env = {**os.environ, "PYTEST_SHARD": bad}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:xdist",
            "tests/test_ci_shards.py",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
