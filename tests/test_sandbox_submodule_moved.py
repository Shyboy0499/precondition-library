"""End-to-end: live git sandbox, injected submodule drift, git-only checker.

The submodule_moved fault has three injected states, one per resolution: the
submodule was never initialised (`init`), its recorded commit drifted from
upstream's pin (`repin`), or upstream dropped it entirely (`remove`). The last is
the one whose wrong resolution is quiet: re-pinning the submodule to its origin's
latest commit *succeeds* as a command while leaving the reference upstream has
dropped in place. So this file pins the directions the other sandbox tests pin --
the fault is present as injected for each state, a wrong resolution is rejected,
a correct one is accepted -- with the remove state's re-pin as the negative
control.

A submodule needs a third repository behind its URL. `inject` builds one inside
the sandbox root from a local path, so the whole test stays offline and
deterministic.

The checker reads its ground truth from refs under `refs/sandbox/`, which the
injector records; the tests never pass the seed to `check`, so the checker cannot
cheat by re-deriving the state from the request.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import Sandbox, create, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.submodule_moved import (
    ORIGIN_DIRNAME,
    SPEC,
    SUBMODULE_PATH,
    state_for_seed,
)

# Seeds chosen because `sample_index(seed, "submodule_moved:inject", 3)` selects
# different states: 4 -> init, 1 -> repin, 0 -> remove. `test_seed_mapping` below
# asserts this, so a change to the salt or the state order cannot silently point
# every test at one state.
SEED_BY_STATE = {"init": 4, "repin": 1, "remove": 0}
STATE_CASES = list(SEED_BY_STATE.items())

_FILE_PROTOCOL = ("-c", "protocol.file.allow=always")


@pytest.fixture
def make_sandbox():
    """Build injected sandboxes and destroy them however the test ends."""
    live: list[Sandbox] = []

    def build(seed: int) -> Sandbox:
        box = create(seed, ["submodule_moved"])
        live.append(box)
        return box

    yield build
    for box in live:
        box.destroy()


def _out(*args: str, cwd) -> str:
    return run_git(args, cwd=cwd).stdout.strip()


def _submodule_status(box: Sandbox) -> str:
    return run_git(("submodule", "status", "--", SUBMODULE_PATH), cwd=box.work).stdout.strip()


def _initialised(box: Sandbox) -> bool:
    """Whether the clone has a checkout for the submodule."""
    status = _submodule_status(box)
    return bool(status) and not status.startswith("-")


def _pin(box: Sandbox, rev: str) -> str:
    """The gitlink SHA `rev` records in the clone, or "" when it records none."""
    line = _out("ls-tree", rev, "--", SUBMODULE_PATH, cwd=box.work)
    return line.split()[2] if line else ""


def _upstream_pin(box: Sandbox) -> str:
    line = _out("ls-tree", "refs/heads/main", "--", SUBMODULE_PATH, cwd=box.upstream)
    return line.split()[2] if line else ""


def _gitmodules_has_entry(box: Sandbox) -> bool:
    result = run_git(
        ("config", "--file", ".gitmodules", "--get", f"submodule.{SUBMODULE_PATH}.path"),
        cwd=box.work,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _origin_grown_commit(box: Sandbox) -> str:
    """The origin's second commit: what the remove state's wrong repin moves to."""
    return _out("rev-parse", "HEAD", cwd=box.root / ORIGIN_DIRNAME)


def _init_submodule(box: Sandbox) -> None:
    """Correct resolution for `init`: fetch the submodule and check it out."""
    run_git(
        (*_FILE_PROTOCOL, "submodule", "update", "--init", "--", SUBMODULE_PATH),
        cwd=box.work,
    )


def _repin_to_upstream(box: Sandbox) -> None:
    """Correct resolution for `repin`: take upstream's pin and check it out."""
    run_git(("merge", "--ff-only", "upstream/main"), cwd=box.work)
    _init_submodule(box)


def _remove_reference(box: Sandbox) -> None:
    """Correct resolution for `remove`: drop the gitlink and .gitmodules entry."""
    run_git(("rm", "-q", "--", SUBMODULE_PATH), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: drop nested library"), cwd=box.work)


def _repin_wrong_on_remove(box: Sandbox) -> None:
    """The plausible wrong answer: move the submodule to its origin's latest.

    This *succeeds*: the submodule updates and the new commit is recorded. It is
    wrong only because upstream has dropped the submodule, so any reference is
    wrong. The test asserts the success before checking it is rejected.
    """
    grown = _origin_grown_commit(box)
    sub = box.work / SUBMODULE_PATH
    run_git(("fetch", "-q", "origin"), cwd=sub)
    run_git(("checkout", "-q", grown), cwd=sub)
    run_git(("add", SUBMODULE_PATH), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: repin nested library"), cwd=box.work)


def _shas(box: Sandbox) -> tuple[str, str, str, str]:
    return (
        _out("rev-parse", "HEAD", cwd=box.work),
        _out("rev-parse", "upstream/main", cwd=box.work),
        _out("rev-parse", "HEAD", cwd=box.upstream),
        _out("rev-parse", "HEAD", cwd=box.root / ORIGIN_DIRNAME),
    )


def test_seed_mapping_is_pinned() -> None:
    """The hard-coded seeds above must keep selecting the states they name."""
    assert {state_for_seed(seed) for seed in SEED_BY_STATE.values()} == set(SEED_BY_STATE)


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_injected_fault_fails_check(state: str, seed: int, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous."""
    box = make_sandbox(seed)
    result = SPEC.check(box)
    assert not result.ok
    assert result.detail


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_injection_shape(state: str, seed: int, make_sandbox) -> None:
    """Each seed injects the state it claims, and leaves a clean worktree."""
    box = make_sandbox(seed)
    assert state_for_seed(seed) == state

    if state == "init":
        assert not _initialised(box)
        assert _pin(box, "HEAD") == _upstream_pin(box)
        assert _upstream_pin(box)
    elif state == "repin":
        assert _initialised(box)
        assert _pin(box, "HEAD") != _upstream_pin(box)
        assert _upstream_pin(box)
    else:
        assert _initialised(box)
        assert _pin(box, "HEAD")
        assert _upstream_pin(box) == ""
    assert run_git(("status", "--porcelain"), cwd=box.work).stdout.strip() == ""


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_observe_matches_injection(state: str, seed: int, make_sandbox) -> None:
    """The three discriminators observe() declares carry the injected state."""
    box = make_sandbox(seed)
    fingerprint = StateFingerprint.observe(box)

    assert fingerprint.has_submodule_reference is True
    if state == "init":
        assert fingerprint.submodule_initialised is False
        assert fingerprint.upstream_still_references_submodule is True
    elif state == "repin":
        assert fingerprint.submodule_initialised is True
        assert fingerprint.submodule_pin_matches_upstream is False
        assert fingerprint.upstream_still_references_submodule is True
    else:
        assert fingerprint.submodule_initialised is True
        assert fingerprint.upstream_still_references_submodule is False


def test_repin_on_remove_is_rejected(make_sandbox) -> None:
    """Re-pin a submodule upstream has dropped; the command works, check says no.

    This is the fault's reason to exist. The re-pin *succeeds* -- the submodule
    is updated and the commit recorded -- so a checker that only asked whether
    the command worked would accept it. It leaves a reference upstream removed,
    so the outcome is wrong.
    """
    box = make_sandbox(SEED_BY_STATE["remove"])
    grown = _origin_grown_commit(box)

    _repin_wrong_on_remove(box)

    assert _pin(box, "HEAD") == grown, "the wrong resolution was supposed to re-pin successfully"
    assert _initialised(box)
    assert _gitmodules_has_entry(box)

    result = SPEC.check(box)
    assert not result.ok, f"a reference upstream dropped was accepted: {result.detail}"
    assert "still referenced" in result.detail


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_correct_resolution_passes_check(state: str, seed: int, make_sandbox) -> None:
    """Run the state's honest minimum; check must accept it."""
    box = make_sandbox(seed)
    if state == "init":
        _init_submodule(box)
        assert _initialised(box)
    elif state == "repin":
        _repin_to_upstream(box)
        assert _pin(box, "HEAD") == _upstream_pin(box)
    else:
        _remove_reference(box)
        assert _pin(box, "HEAD") == ""
        assert not _gitmodules_has_entry(box)

    result = SPEC.check(box)
    assert result.ok, result.detail
    assert run_git(("status", "--porcelain"), cwd=box.work).stdout.strip() == ""


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_same_seed_reproduces_commit_shas(state: str, seed: int, make_sandbox) -> None:
    """Same seed, same content: every recorded SHA must match."""
    first = make_sandbox(seed)
    shas_first = _shas(first)
    first.destroy()
    second = make_sandbox(seed)
    assert _shas(second) == shas_first


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_observe_does_not_mutate(state: str, seed: int, make_sandbox) -> None:
    box = make_sandbox(seed)
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert after.has_submodule_reference is True


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(SEED_BY_STATE["remove"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
