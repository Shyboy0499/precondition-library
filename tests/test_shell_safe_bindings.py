"""Repository-derived values are bound only when a shell cannot read them as code (ADR-0040).

`substitute` pastes a bound value into a probe or body as written, and both run under
`bash -c`. On a checkout (#181) the values come from the repository: the upstream's default
branch is whatever its owner names it, and a `.gitmodules` path is whatever the file says.
Git allows `;`, `$`, `(`, `>` and quotes in a branch name. These tests pin that such a value
is left unbound, so a program needing it is not applicable, and that nothing it carries runs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from precondition_library.checkout import open_checkout
from precondition_library.program import Predicate
from precondition_library.runtime.probes import (
    bindings,
    evaluate_predicates,
    repository_bindings,
    shell_safe,
)
from precondition_library.sandbox import gitmodules_path

_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=_ENV)


def _clone_of(tmp_path: Path, default_branch: str) -> Path:
    """A clone whose remote's default branch is `default_branch`."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "README").write_text("x\n", encoding="utf-8")
    _git(upstream, "add", "README")
    _git(upstream, "commit", "-q", "-m", "init")
    if default_branch != "main":
        _git(upstream, "branch", default_branch)
        _git(upstream, "symbolic-ref", "HEAD", f"refs/heads/{default_branch}")
    _git(tmp_path, "clone", "-q", str(upstream), "work")
    return tmp_path / "work"


@pytest.mark.parametrize(
    "value", ["main", "trunk", "release/2026.10", "vendor/libcore", ".deps/lib", "feature+x"]
)
def test_ordinary_names_are_shell_safe(value: str) -> None:
    assert shell_safe(value)


@pytest.mark.parametrize(
    "value",
    ["", "x;>PWNED", "a b", "café", "$(id)", "x`id`", "x|y", "x&y", "'x'", "../x", "a/../b"]
    + ["-rf", "/etc/passwd"],
)
def test_a_value_the_shell_could_read_as_code_is_not(value: str) -> None:
    assert not shell_safe(value)


def test_a_hostile_default_branch_is_left_unbound_and_never_runs(tmp_path: Path) -> None:
    """The measured case: before this, the probe created `PWNED` in the checkout."""
    work = _clone_of(tmp_path, "x;>PWNED")
    assert "upstream_branch" not in repository_bindings(work)
    env = open_checkout(work)
    try:
        probe = Predicate(
            name="upstream_exists",
            description="upstream's branch resolves",
            probe="git rev-parse --verify {upstream_remote}/{upstream_branch}",
        )
        result = evaluate_predicates([probe], env, kind="precondition")
    finally:
        env.destroy()
    assert not result.ok
    assert "not applicable" in result.predicates[0].observed
    assert not (work / "PWNED").exists(), "the branch name ran as shell"


def test_an_ordinary_default_branch_is_still_bound(tmp_path: Path) -> None:
    work = _clone_of(tmp_path, "trunk")
    assert repository_bindings(work)["upstream_branch"] == "trunk"


def _with_gitmodules(work: Path, path: str) -> None:
    _git(work, "config", "--file", ".gitmodules", "submodule.lib.path", path)
    _git(work, "config", "--file", ".gitmodules", "submodule.lib.url", "../lib")


def test_a_gitmodules_path_is_read_whole_and_a_hostile_one_is_not_bound(tmp_path: Path) -> None:
    """`my lib` used to bind as `lib`: a valid-looking path that is not the submodule."""
    work = _clone_of(tmp_path, "main")
    _with_gitmodules(work, "my lib")
    assert gitmodules_path(work) == "my lib"
    assert "submodule_path" not in repository_bindings(work), "a space is not bound"

    _with_gitmodules(work, "vendor/lib$(>PWNED)")
    assert gitmodules_path(work) == "vendor/lib$(>PWNED)"
    assert "submodule_path" not in repository_bindings(work)

    _with_gitmodules(work, "vendor/libcore")
    assert repository_bindings(work)["submodule_path"] == "vendor/libcore"


def test_the_harness_screens_the_same_way(make_sandbox) -> None:
    """`bindings` reads `.gitmodules` on a harness sandbox too, so it screens identically."""
    box = make_sandbox(0, [])
    _with_gitmodules(box.work, "lib;>PWNED")
    assert "submodule_path" not in bindings(box)
    assert repository_bindings(box.work) == bindings(box)
