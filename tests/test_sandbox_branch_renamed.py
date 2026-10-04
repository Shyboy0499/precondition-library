"""End-to-end: live git sandbox, renamed upstream branch, git-only checker (#190, step 2).

Upstream renames its default branch and moves on with one commit there; the clone
still follows the old name. Each seed selects one of three states -- `plain`,
`local_work` (a local commit upstream lacks) and `name_taken` (a local branch already
has the new name, with a commit of its own) -- and the sandbox is left as the trusted
pre-fetch leaves a checkout: fetched, upstream's `HEAD` recorded, nothing pruned.

`check` grades the outcome, not the method. The tracked branch must exist in the
upstream repo -- verified against upstream itself, not the clone's stale
remote-tracking ref -- and its tip must be contained; the local commit's work must
still be in the tree; and the side branch's commit must still be reachable. The
tests never pass the seed to `check`, so it cannot re-derive the target from it.
"""

from __future__ import annotations

import pytest

from precondition_library.runtime.probes import bindings, repository_bindings
from precondition_library.sandbox import Sandbox, run_git, upstream_ref
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.branch_renamed import (
    INJECTED_STATES,
    SPEC,
    renamed_branch_for_seed,
    state_for_seed,
)

SEED_FOR = {"plain": 0, "local_work": 1, "name_taken": 6}
OLD_BRANCH = "main"


def _git(box: Sandbox, *args: str) -> str:
    return run_git(args, cwd=box.work).stdout.strip()


def _upstream_branches(box: Sandbox) -> set[str]:
    out = run_git(
        ("for-each-ref", "--format=%(refname:short)", "refs/heads"), cwd=box.upstream
    ).stdout
    return set(out.split())


def _retrack(box: Sandbox, name: str) -> None:
    _git(box, "branch", f"--set-upstream-to=upstream/{name}", OLD_BRANCH)


def test_the_seeds_cover_every_state() -> None:
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(INJECTED_STATES)
    assert all(state_for_seed(seed) == state for state, seed in SEED_FOR.items())


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_injected_fault_fails_check(state: str, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous."""
    box = make_sandbox(SEED_FOR[state], ["branch_renamed"])
    result = SPEC.check(box)
    assert not result.ok
    assert f"refs/heads/{OLD_BRANCH}" in result.detail, "graded as the fault: the old name"


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_observe_matches_injection(state: str, make_sandbox) -> None:
    seed = SEED_FOR[state]
    new_name = renamed_branch_for_seed(seed)
    box = make_sandbox(seed, ["branch_renamed"])
    seen = StateFingerprint.observe(box)

    assert _upstream_branches(box) == {new_name}
    assert (seen.branch, seen.tracked_branch) == (OLD_BRANCH, OLD_BRANCH), "the stale wiring"
    assert seen.upstream_default_branch == new_name, "what the pre-fetch recorded"
    assert seen.upstream_ahead == 1, "upstream moved on after the rename"
    assert seen.upstream_behind == (1 if state == "local_work" else 0)
    expected_branches = [OLD_BRANCH, new_name] if state == "name_taken" else [OLD_BRANCH]
    assert seen.local_branches == sorted(expected_branches)


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_the_harness_and_a_checkout_agree_on_upstream(state: str, make_sandbox) -> None:
    """What `repository_bindings` derives on a checkout is what the harness binds."""
    box = make_sandbox(SEED_FOR[state], ["branch_renamed"])
    new_name = renamed_branch_for_seed(SEED_FOR[state])
    assert upstream_ref(box) == f"upstream/{new_name}"
    derived = repository_bindings(box.work)
    assert (derived["upstream_remote"], derived["upstream_branch"]) == ("upstream", new_name)
    assert bindings(box)["upstream_branch"] == new_name


def test_a_sandbox_with_no_rename_still_binds_main(make_sandbox) -> None:
    box = make_sandbox(0, [])
    assert upstream_ref(box) == "upstream/main"
    assert bindings(box)["upstream_branch"] == "main"


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_tracking_the_stale_old_name_fails(state: str, make_sandbox) -> None:
    """The quiet wrong fix: the unpruned `upstream/main` still resolves, so this succeeds."""
    box = make_sandbox(SEED_FOR[state], ["branch_renamed"])
    _retrack(box, OLD_BRANCH)
    assert _git(box, "rev-parse", "--abbrev-ref", "@{upstream}") == f"upstream/{OLD_BRANCH}"
    result = SPEC.check(box)
    assert not result.ok and "does not exist" in result.detail


def test_tracking_a_branch_upstream_never_had_fails(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["plain"], ["branch_renamed"])
    _git(box, "config", f"branch.{OLD_BRANCH}.merge", "refs/heads/legacy")
    result = SPEC.check(box)
    assert not result.ok and "does not exist" in result.detail


def test_retracking_without_taking_upstreams_commit_fails(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["plain"], ["branch_renamed"])
    _retrack(box, renamed_branch_for_seed(SEED_FOR["plain"]))
    result = SPEC.check(box)
    assert not result.ok and "not contained" in result.detail


def test_resetting_onto_the_new_branch_loses_the_local_work(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["local_work"], ["branch_renamed"])
    new_name = renamed_branch_for_seed(SEED_FOR["local_work"])
    _git(box, "reset", "-q", "--hard", f"upstream/{new_name}")
    _retrack(box, new_name)
    result = SPEC.check(box)
    assert not result.ok and "lost" in result.detail


def test_forcing_the_rename_over_the_taken_name_loses_its_commit(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["name_taken"], ["branch_renamed"])
    new_name = renamed_branch_for_seed(SEED_FOR["name_taken"])
    _git(box, "branch", "-M", new_name)
    _git(box, "branch", f"--set-upstream-to=upstream/{new_name}", new_name)
    _git(box, "merge", "-q", "--ff-only", f"upstream/{new_name}")
    result = SPEC.check(box)
    assert not result.ok and "lost its commit" in result.detail


@pytest.mark.parametrize("state", ["plain", "name_taken"])
def test_retrack_and_fast_forward_passes_without_local_work(state: str, make_sandbox) -> None:
    box = make_sandbox(SEED_FOR[state], ["branch_renamed"])
    new_name = renamed_branch_for_seed(SEED_FOR[state])
    _retrack(box, new_name)
    _git(box, "merge", "-q", "--ff-only", f"upstream/{new_name}")
    result = SPEC.check(box)
    assert result.ok, result.detail


def test_retrack_and_merge_keeps_local_work(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["local_work"], ["branch_renamed"])
    new_name = renamed_branch_for_seed(SEED_FOR["local_work"])
    _retrack(box, new_name)
    _git(box, "merge", "-q", "--no-edit", f"upstream/{new_name}")
    result = SPEC.check(box)
    assert result.ok, result.detail


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_same_seed_reproduces_state(state: str, make_sandbox) -> None:
    seed = SEED_FOR[state]

    def shas(box: Sandbox) -> tuple[str, ...]:
        return tuple(_git(box, "for-each-ref", "--format=%(refname) %(objectname)").splitlines())

    first = make_sandbox(seed, ["branch_renamed"])
    before = shas(first)
    first.destroy()
    assert shas(make_sandbox(seed, ["branch_renamed"])) == before


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_observe_does_not_mutate(state: str, make_sandbox) -> None:
    box = make_sandbox(SEED_FOR[state], ["branch_renamed"])
    assert StateFingerprint.observe(box) == StateFingerprint.observe(box)


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["plain"], ["branch_renamed"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
