"""lockmerge as git uses it: installed as a merge driver, during `git merge`, and `resolve`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

ROOT = Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "lockmerge" / "src"), env.get("PYTHONPATH", "")]
    )
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, env=_env(), capture_output=True, text=True, check=check
    )


def _lockmerge(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "lockmerge", *args],
        cwd=repo,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _lock(extra: dict[str, str]) -> str:
    packages: dict[str, Any] = {
        "": {
            "name": "app",
            "dependencies": {"left-pad": "^1.0.0", **{k: f"^{v}" for k, v in extra.items()}},
        },
        "node_modules/left-pad": {"version": "1.1.0"},
    }
    for name, version in extra.items():
        packages[f"node_modules/{name}"] = {"version": version}
    packages = {"": packages[""], **dict(sorted((k, v) for k, v in packages.items() if k))}
    packages[""]["dependencies"] = dict(sorted(packages[""]["dependencies"].items()))
    lock = {"name": "app", "lockfileVersion": 3, "requires": True, "packages": packages}
    return json.dumps(lock, indent=2) + "\n"


def _repo(tmp_path: Path, ours: dict[str, str], theirs: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "package-lock.json").write_text(_lock({}), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "package-lock.json").write_text(_lock(theirs), encoding="utf-8")
    _git(repo, "commit", "-qam", "theirs")
    _git(repo, "checkout", "-q", "main")
    (repo / "package-lock.json").write_text(_lock(ours), encoding="utf-8")
    _git(repo, "commit", "-qam", "ours")
    return repo


def test_install_then_merge_resolves_a_lock_file_conflict(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ours={"zod": "3.22.0"}, theirs={"chalk": "5.3.0"})
    installed = _lockmerge(repo, "install")
    assert installed.returncode == 0, installed.stderr
    assert "package-lock.json merge=lockmerge" in (repo / ".gitattributes").read_text()
    merged = _git(repo, "merge", "-q", "--no-edit", "feature", check=False)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    lock = json.loads((repo / "package-lock.json").read_text(encoding="utf-8"))
    assert set(lock["packages"]) == {
        "",
        "node_modules/chalk",
        "node_modules/left-pad",
        "node_modules/zod",
    }


def test_an_unsafe_merge_is_left_conflicted_with_the_reason(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ours={"zod": "3.22.0"}, theirs={"zod": "3.23.0"})
    assert _lockmerge(repo, "install").returncode == 0
    merged = _git(repo, "merge", "--no-edit", "feature", check=False)
    assert merged.returncode != 0
    text = (repo / "package-lock.json").read_text(encoding="utf-8")
    assert "<<<<<<< ours" in text and ">>>>>>> theirs" in text
    assert "zod: base absent, ours 3.22.0, theirs 3.23.0" in merged.stderr


def test_resolve_finishes_a_conflict_git_left_behind(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ours={"zod": "3.22.0"}, theirs={"chalk": "5.3.0"})
    merged = _git(repo, "merge", "--no-edit", "feature", check=False)  # no driver installed
    assert merged.returncode != 0
    resolved = _lockmerge(repo, "resolve")
    assert resolved.returncode == 0, resolved.stderr
    assert "resolved package-lock.json and staged it" in resolved.stderr
    assert _git(repo, "ls-files", "-u").stdout == ""
    lock = json.loads((repo / "package-lock.json").read_text(encoding="utf-8"))
    assert "node_modules/chalk" in lock["packages"] and "node_modules/zod" in lock["packages"]


def test_check_prints_the_merge_without_touching_git(tmp_path: Path) -> None:
    for name, extra in (("base", {}), ("ours", {"zod": "3.22.0"}), ("theirs", {"chalk": "5.3.0"})):
        (tmp_path / f"{name}.json").write_text(_lock(extra), encoding="utf-8")
    done = _lockmerge(
        tmp_path, "check", "base.json", "ours.json", "theirs.json", "--name", "package-lock.json"
    )
    assert done.returncode == 0, done.stderr
    assert "node_modules/chalk" in json.loads(done.stdout)["packages"]
