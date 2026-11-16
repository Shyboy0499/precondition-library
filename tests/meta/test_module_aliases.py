"""The old `precondition_library.bench.<module>` paths still work after the reorganisation.

Frozen pre-registrations, committed results and their verification scripts quote those paths
(`python -m precondition_library.bench.real_merges`), and a registration cannot be edited without
breaking its pin. So each old path is an alias: importing it gives the moved module itself, and
running it with `-m` runs the moved module.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "src" / "precondition_library" / "bench"
OLD = sorted(p.stem for p in BENCH.glob("*.py") if p.name != "__init__.py")


def test_every_old_module_has_an_alias() -> None:
    """46 modules moved; each left an alias behind, and no code was left in `bench/`."""
    assert len(OLD) == 46
    for name in OLD:
        text = (BENCH / f"{name}.py").read_text(encoding="utf-8")
        assert "alias(__name__," in text, f"bench/{name}.py is not an alias"
        assert len(text.splitlines()) < 12, f"bench/{name}.py holds code, not just an alias"


@pytest.mark.parametrize("name", OLD)
def test_the_old_path_is_the_moved_module(name: str) -> None:
    old = importlib.import_module(f"precondition_library.bench.{name}")
    assert old.__name__ != f"precondition_library.bench.{name}", "the alias did not resolve"
    assert importlib.import_module(old.__name__) is old, "two module objects for one module"


def test_running_an_old_path_runs_the_moved_module() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    old = subprocess.run(
        [sys.executable, "-m", "precondition_library.bench.lock_oracle", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    new = subprocess.run(
        [sys.executable, "-m", "precondition_library.studies.lock_oracle", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert old.stdout == new.stdout and "--out" in old.stdout
