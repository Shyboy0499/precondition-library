"""The compile prompt's path-list rule (ADR-0038): git quotes paths, and not one way.

Replicate 3's `stash` program mis-fired on held-out seed 3038 (`results/heldout-2026-10-16/`)
because its precondition compared `git status --porcelain`, which quotes a path with a space,
against `git diff --name-only`, which does not. These tests run the prompt's own example probe
and that committed probe on real repositories whose colliding untracked file has a space or a
non-ASCII name, so the rule is pinned by what git does, not by what the prompt says.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from precondition_library.agents.compile import SYSTEM_PROMPT
from precondition_library.program import Predicate
from precondition_library.runtime.probes import evaluate_predicates, substitute

PARAMETERS = {"upstream_remote": "origin", "upstream_branch": "main"}

RUN_13_PROBE = (
    "! comm -12 <(git status --porcelain --untracked-files=all | sed -n 's/^?? //p' | sort) "
    "<(git diff --name-only HEAD..{upstream_remote}/{upstream_branch} | sort) | grep -q ."
)
"""`no_untracked_collision_with_incoming`, as replicate 3's library admitted it."""

RUN_11_PROBE = (
    'test -z "$(git diff --name-only HEAD..{upstream_remote}/{upstream_branch} | while IFS= read '
    '-r p; do if [ -e "$p" ] && ! git ls-files --error-unmatch -- "$p" >/dev/null 2>&1; '
    'then printf \'%s\\n\' "$p"; fi; done)"'
)
"""`no_untracked_file_collides_with_upstream`, as replicate 1's commit program admitted it."""

PATHS = ["notes/scratch.txt", "scratch notes.md", "café.md"]


def _example_probe() -> str:
    """The probe the rule shows, read out of the prompt as YAML, as a model would read it."""
    lines = SYSTEM_PROMPT.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip() == "probe: |-" and "-z" in lines[i + 2]
    )
    end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith(" " * 8))
    block = textwrap.dedent("\n".join(lines[start:end]))
    probe = yaml.safe_load(block)["probe"]
    assert isinstance(probe, str)
    return probe


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=_env(cwd))


def _env(cwd: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(cwd),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


def _repository(tmp_path: Path, upstream_adds: str, untracked: str) -> Path:
    """A clone one upstream commit behind, which adds `upstream_adds`; `untracked` is local."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "app.py").write_text("a\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "init")
    _git(tmp_path, "clone", "-q", str(upstream), "work")
    added = upstream / upstream_adds
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("upstream\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-qm", "add")
    work = tmp_path / "work"
    _git(work, "fetch", "-q", "origin")
    local = work / untracked
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("mine\n", encoding="utf-8")
    return work


def _holds(probe: str, work: Path) -> bool:
    command = substitute(probe, PARAMETERS)
    return subprocess.run(["bash", "-c", command], cwd=work, env=_env(work)).returncode == 0


def test_the_compile_prompt_states_the_path_rule() -> None:
    assert "Git does not print paths one way" in SYSTEM_PROMPT
    assert "git ls-files --others --exclude-standard -z" in SYSTEM_PROMPT
    assert "\0" not in SYSTEM_PROMPT, "the example's `\\0` must reach the model as two characters"


@pytest.mark.parametrize("path", PATHS)
def test_the_prompts_example_sees_a_collision_on_any_path(tmp_path: Path, path: str) -> None:
    """ "No untracked file collides" must not hold when one does, whatever its name."""
    assert not _holds(_example_probe(), _repository(tmp_path, path, path))


@pytest.mark.parametrize("path", PATHS)
def test_the_prompts_example_holds_when_nothing_collides(tmp_path: Path, path: str) -> None:
    assert _holds(_example_probe(), _repository(tmp_path, path, f"elsewhere/{path}"))


@pytest.mark.parametrize(
    ("probe", "path", "sees_it"),
    [
        (RUN_13_PROBE, "notes/scratch.txt", True),
        (RUN_13_PROBE, "scratch notes.md", False),
        (RUN_13_PROBE, "café.md", True),
        (RUN_11_PROBE, "notes/scratch.txt", True),
        (RUN_11_PROBE, "scratch notes.md", True),
        (RUN_11_PROBE, "café.md", False),
    ],
    ids=[
        "run-13-plain",
        "run-13-space",
        "run-13-non-ascii",
        "run-11-plain",
        "run-11-space",
        "run-11-non-ascii",
    ],
)
def test_two_admitted_probes_miss_a_collision_on_a_quoted_path(
    tmp_path: Path, probe: str, path: str, sees_it: bool
) -> None:
    """The controls: each committed probe is right on the shipped path and wrong on one other.

    Replicate 3's compares `status`, which quotes a space, with `diff`, which does not; both
    escape a non-ASCII name alike, so that one it sees. Replicate 1's tests `diff`'s printed
    name as a file, so it sees a space and misses the escaped non-ASCII name.
    """
    assert _holds(probe, _repository(tmp_path, path, path)) is not sees_it


@pytest.mark.parametrize(("seed", "collides"), [(3038, True), (3010, False)])
def test_the_prompts_example_decides_held_out_states_through_the_runtime(
    make_sandbox, seed: int, collides: bool
) -> None:
    """The held-out states with `scratch notes.md` untracked: 3038 collides, 3010 does not.

    Run through `evaluate_predicates`, so the example is also bound, guarded and snapshotted
    exactly as an admitted precondition is.
    """
    box = make_sandbox(seed, ["dirty_tree"])
    predicate = Predicate(name="no_collision", description="none collides", probe=_example_probe())
    assert evaluate_predicates([predicate], box, kind="precondition").ok is not collides
