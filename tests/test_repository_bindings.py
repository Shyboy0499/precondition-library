"""Parameter bindings derived from an existing checkout (issue #181, first item).

`runtime.probes.bindings` is the harness's fixed vocabulary: `upstream`, `main` and the
recorded submodule path, because `sandbox.create` builds every sandbox that way.
`repository_bindings` reads the same names from a repository. These tests pin:

* on every harness sandbox the two agree, so a program compiled in the harness binds
  the same values on a checkout built the harness's way;
* on checkouts built otherwise -- a plain clone of `origin`, a fork with both remotes, a
  `master` or `trunk` default branch -- each value is read from the repository;
* a value that cannot be derived is absent, never guessed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from precondition_library.runtime.probes import bindings, repository_bindings
from precondition_library.sandbox import run_git
from precondition_library.tasks.faults import FAULTS, build_sandbox
from precondition_library.tasks.registry import ambiguous_intents

MEASURED = sorted(intent.fault for intent in ambiguous_intents())


def _seeds_per_state(fault: str) -> list[int]:
    seeds: dict[str, int] = {}
    for seed in range(200):
        state = FAULTS[fault].variant_for_seed(seed)
        if state is not None:
            seeds.setdefault(state, seed)
    return sorted(seeds.values())


@pytest.mark.parametrize(
    ("faults", "seed"),
    [([], 0)] + [([fault], seed) for fault in MEASURED for seed in _seeds_per_state(fault)],
)
def test_on_a_harness_sandbox_the_derived_values_are_the_fixed_ones(faults, seed) -> None:
    box = build_sandbox(seed, faults)
    try:
        assert repository_bindings(box.work) == bindings(box)
    finally:
        box.destroy()


def _git(cwd: Path, *args: str) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _origin(root: Path, name: str, branch: str) -> Path:
    """A repository with one commit on `branch`, to clone from."""
    repo = root / name
    run_git(("-c", f"init.defaultBranch={branch}", "init", "-q", str(repo)), cwd=root)
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.invalid")
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_a_plain_clone_binds_origin_and_its_default_branch(tmp_path) -> None:
    origin = _origin(tmp_path, "project", "trunk")
    work = tmp_path / "work"
    run_git(("clone", "-q", str(origin), str(work)), cwd=tmp_path)

    assert repository_bindings(work) == {
        "work_dir": str(work),
        "upstream_remote": "origin",
        "upstream_branch": "trunk",
    }


def test_a_fork_prefers_upstream_over_origin(tmp_path) -> None:
    fork = _origin(tmp_path, "fork", "main")
    upstream = _origin(tmp_path, "upstream-project", "master")
    work = tmp_path / "work"
    run_git(("clone", "-q", str(fork), str(work)), cwd=tmp_path)
    _git(work, "remote", "add", "upstream", str(upstream))
    _git(work, "fetch", "-q", "upstream")

    found = repository_bindings(work)
    assert found["upstream_remote"] == "upstream"
    assert found["upstream_branch"] == "master", "no recorded HEAD, so the fallback it has"


def test_the_tracked_remote_decides_among_several(tmp_path) -> None:
    first = _origin(tmp_path, "first", "main")
    second = _origin(tmp_path, "second", "develop")
    work = tmp_path / "work"
    run_git(("clone", "-q", "-o", "alpha", str(first), str(work)), cwd=tmp_path)
    _git(work, "remote", "add", "beta", str(second))
    _git(work, "fetch", "-q", "beta")
    _git(work, "checkout", "-q", "-b", "feature", "--track", "beta/develop")

    found = repository_bindings(work)
    assert found["upstream_remote"] == "beta"
    assert "upstream_branch" not in found, "beta records no HEAD and has no main or master"


def test_nothing_is_guessed_when_the_repository_does_not_say(tmp_path) -> None:
    lonely = _origin(tmp_path, "lonely", "main")
    assert repository_bindings(lonely) == {"work_dir": str(lonely)}, "no remote at all"

    first = _origin(tmp_path, "first", "main")
    second = _origin(tmp_path, "second", "main")
    work = tmp_path / "work"
    run_git(("init", "-q", str(work)), cwd=tmp_path)
    _git(work, "remote", "add", "a", str(first))
    _git(work, "remote", "add", "b", str(second))
    assert "upstream_remote" not in repository_bindings(work), "two remotes, no signal"


def test_the_submodule_path_comes_from_gitmodules(tmp_path) -> None:
    repo = _origin(tmp_path, "with-submodule", "main")
    (repo / ".gitmodules").write_text(
        '[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = ../lib\n', encoding="utf-8"
    )
    assert repository_bindings(repo)["submodule_path"] == "vendor/lib"
