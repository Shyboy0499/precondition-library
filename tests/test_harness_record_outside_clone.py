"""The harness keeps its bookkeeping out of the clone the agent works in (issue #161).

The first live run found the agent reading `refs/sandbox/*`: a double-injection marker,
the submodule path, and the post-injection ref snapshot. They held in every sandbox and
in no real repository, so a compiled precondition anchored on one could pass admission
without diagnosing anything. All three now live in `Sandbox.recorded`, which
the harness holds in memory. These tests pin that no fault leaves anything under
`refs/sandbox/`, and that what the refs used to do still works without them.
"""

from __future__ import annotations

import pytest

from precondition_library.runtime.probes import bindings
from precondition_library.sandbox import RECORDED_SUBMODULE_PATH, run_git
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.faults.submodule_moved import SUBMODULE_PATH
from precondition_library.tasks.invariants import RECORDED_REFS_AT_START

REMOVE_SEED = 0  # submodule_moved seed 0 injects `remove`


def _harness_refs(repo) -> str:
    return run_git(("for-each-ref", "refs/sandbox/"), cwd=repo).stdout.strip()


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("seed", [0, 1])
def test_no_fault_leaves_harness_refs_in_either_repository(fault, seed, make_sandbox) -> None:
    box = make_sandbox(seed, [fault])

    assert _harness_refs(box.work) == "", "the agent's clone carries harness bookkeeping"
    assert _harness_refs(box.upstream) == ""
    assert RECORDED_REFS_AT_START in box.recorded, "the snapshot moved, it was not dropped"


def test_a_second_injection_is_still_refused(make_sandbox) -> None:
    """The double-injection guard reads the in-memory record instead of a ref."""
    box = make_sandbox(0, ["diverged"])

    with pytest.raises(RuntimeError, match="already has a diverged fault injected"):
        FAULTS["diverged"].inject(0, box)


def test_the_submodule_path_still_binds_after_a_correct_removal(make_sandbox) -> None:
    """Why the path was recorded at all: removal deletes the `.gitmodules` entry."""
    box = make_sandbox(REMOVE_SEED, ["submodule_moved"])
    assert box.recorded[RECORDED_SUBMODULE_PATH] == SUBMODULE_PATH

    run_git(("rm", "-q", "-f", "--", SUBMODULE_PATH), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: drop nested library"), cwd=box.work)
    shown = run_git(("config", "--file", ".gitmodules", "--list"), cwd=box.work, check=False)
    assert SUBMODULE_PATH not in shown.stdout, "the removal should have erased the evidence"

    assert bindings(box)["submodule_path"] == SUBMODULE_PATH
