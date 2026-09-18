"""End-to-end: live git sandbox, injected divergence, gold body, git-only checker.

This is the first test that ties the declarative state grid to a real repository.
The grid in `conftest.py` says which fingerprint should resolve to which
resolution; these tests build the real-world equivalent with `sandbox.create`,
observe it with `StateFingerprint.observe`, run a hand-written gold body, and
require `DivergedFault.check` to accept it.

The reverse direction is the point of the negative controls. A checker that only
ever says yes makes every result below it meaningless -- issue #9 -- so the same
checker must reject an untouched sandbox, and must reject `reset --hard` on the
disjoint and overlapping states, where the command *succeeds* while destroying
the user's work.
"""

from __future__ import annotations

import subprocess

import pytest
from conftest import GOLD_CASES, gold_program

from precondition_library.runtime.probes import SHELL
from precondition_library.sandbox import Sandbox, git_env, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.diverged import INTENT, SPEC, STATE_VARIANT

# The seed in `GOLD_CASES` is chosen because `sample_index(seed,
# "diverged:inject", 3)` selects that injected state; the resolution is the one
# `conftest.py`'s grid declares for the real-world equivalent, so a mismatch here
# is a live repo disagreeing with the grid.
CASES = GOLD_CASES

# The discard body is right for the empty state and wrong for the other two:
# there it is the `reset --hard` that looks like success and loses work.
DESTROYS_LOCAL_WORK = ["disjoint_files", "overlapping_files"]


def _run_body(variant: str, box: Sandbox) -> None:
    """Run a gold body with its parameters substituted.

    A full templating engine is not needed: the bodies reference exactly the
    three declared parameters, so `str.format` is the whole substitution.

    The body goes through `SHELL`, the interpreter `probes.py` declares, rather
    than `shell=True`. These are multi-line POSIX bodies: `shell=True` picks the
    platform's own shell, and on Windows that is `cmd.exe`, which runs the first
    line, discards the rest, and returns **0**. The body would appear to succeed
    while the assertions below failed for a reason naming the gold body instead.
    """
    body = gold_program(variant).body.format(
        work_dir=str(box.work), upstream_remote="upstream", upstream_branch="main"
    )
    result = subprocess.run(
        [*SHELL, body],
        cwd=box.work,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_env(),
    )
    assert result.returncode == 0, f"{variant} body failed:\n{result.stdout}\n{result.stderr}"


def _commit_shas(box: Sandbox) -> tuple[str, str, str, str]:
    return (
        run_git(("rev-parse", "HEAD"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "upstream/main"), cwd=box.work).stdout.strip(),
        run_git(("rev-parse", "refs/heads/main"), cwd=box.upstream).stdout.strip(),
        run_git(("rev-parse", "refs/sandbox/local-tip"), cwd=box.work).stdout.strip(),
    )


@pytest.mark.parametrize("state", list(CASES))
def test_observed_fingerprint_matches_the_grid(state: str, make_sandbox, state_grid) -> None:
    """Live git must fingerprint as the declarative grid says it should."""
    seed, expected_variant = CASES[state]
    box = make_sandbox(seed, ["diverged"])
    fingerprint = StateFingerprint.observe(box)
    declared = state_grid["sync_fork_with_upstream"][state]

    resolved = INTENT.correct_variant(fingerprint)
    assert resolved is not None, f"{state}: no variant matched {fingerprint}"
    assert resolved.id == expected_variant
    # The declared grid must resolve the same way, or the live equivalent is not
    # an equivalent of the state this test claims to build.
    assert STATE_VARIANT[state] == expected_variant
    assert INTENT.correct_variant(declared).id == expected_variant
    assert fingerprint.has_local_only_commits == declared.has_local_only_commits
    assert fingerprint.local_touched_files == declared.local_touched_files
    assert fingerprint.upstream_touched_files == declared.upstream_touched_files
    assert fingerprint.conflicting_files == declared.conflicting_files


@pytest.mark.parametrize("state", list(CASES))
def test_matching_gold_body_passes_check(state: str, make_sandbox) -> None:
    seed, variant = CASES[state]
    box = make_sandbox(seed, ["diverged"])
    _run_body(variant, box)
    result = SPEC.check(box)
    assert result.ok, result.detail


@pytest.mark.parametrize("state", list(CASES))
def test_check_rejects_untouched_sandbox(state: str, make_sandbox) -> None:
    """The injected fault must be the only reason the checker can pass."""
    seed, _ = CASES[state]
    box = make_sandbox(seed, ["diverged"])
    result = SPEC.check(box)
    assert not result.ok
    assert result.detail


@pytest.mark.parametrize("state", DESTROYS_LOCAL_WORK)
def test_wrong_program_fails_check(state: str, make_sandbox) -> None:
    """`reset --hard` succeeds on these states and destroys work; check must say so."""
    seed, _ = CASES[state]
    box = make_sandbox(seed, ["diverged"])
    _run_body("discard", box)
    result = SPEC.check(box)
    assert not result.ok, f"{state}: reset --hard was accepted"
    assert "discard" in result.detail


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_same_seed_reproduces_commit_shas(seed: int, make_sandbox) -> None:
    """Same seed, same content: every commit SHA must match."""
    first = make_sandbox(seed, ["diverged"])
    shas_first = _commit_shas(first)
    first.destroy()
    second = make_sandbox(seed, ["diverged"])
    assert _commit_shas(second) == shas_first


def test_observe_does_not_mutate(make_sandbox) -> None:
    box = make_sandbox(2, ["diverged"])
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert not after.dirty_worktree


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(1, ["diverged"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
