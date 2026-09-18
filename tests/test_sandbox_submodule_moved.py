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

import precondition_library.sandbox as sandbox_module
from precondition_library.sandbox import Sandbox, run_git
from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults import build_sandbox
from precondition_library.tasks.faults.submodule_moved import (
    INTENT,
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
    """The hard-coded seeds above must keep selecting the states they name.

    Admission's same-intent negative class reads `SPEC.variant_for_seed`, which
    returns the injected state name as the resolution. That is only sound because
    each state is named after the resolution it requires, so the names are the
    intent's declared variant ids; asserted here rather than assumed.
    """
    assert {state_for_seed(seed) for seed in SEED_BY_STATE.values()} == set(SEED_BY_STATE)

    declared = {variant.id for variant in INTENT.variants}
    for state, seed in SEED_BY_STATE.items():
        assert SPEC.variant_for_seed(seed) == state
        assert state in declared


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_injected_fault_fails_check(state: str, seed: int, make_sandbox) -> None:
    """A fresh injection that checked as ok would make the checker vacuous."""
    box = make_sandbox(seed, ["submodule_moved"])
    result = SPEC.check(box)
    assert not result.ok
    assert result.detail


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_injection_shape(state: str, seed: int, make_sandbox) -> None:
    """Each seed injects the state it claims, and leaves a clean worktree."""
    box = make_sandbox(seed, ["submodule_moved"])
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
    box = make_sandbox(seed, ["submodule_moved"])
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
    box = make_sandbox(SEED_BY_STATE["remove"], ["submodule_moved"])
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
    box = make_sandbox(seed, ["submodule_moved"])
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
    """Same seed, same content: every recorded SHA must match.

    This compares two builds at the **same root**, so it accepts anything that
    enters the committed content from the root path -- which is exactly what an
    absolute submodule URL used to do, and why it passed while the sandbox was not
    reproducible across checkouts. `test_content_is_independent_of_where_it_was_built`
    below is the assertion that catches that; this one catches a seed-dependent
    change in the injection itself.
    """
    first = make_sandbox(seed, ["submodule_moved"])
    shas_first = _shas(first)
    first.destroy()
    second = make_sandbox(seed, ["submodule_moved"])
    assert _shas(second) == shas_first


def test_content_is_independent_of_where_it_was_built(tmp_path, monkeypatch) -> None:
    """The determinism claim *across checkouts*, not just twice inside one root (#72).

    A sandbox built in this checkout has to be byte-identical to one built in
    yours, or "both arms face identical environments" and "a re-run reproduces the
    episode" are claims about one machine. The injector used to record the
    submodule's absolute origin path in the committed `.gitmodules`, which put
    every commit SHA of this fault at the mercy of where the sandbox happened to
    be built -- measured as a full HEAD divergence between two roots.

    The URL is now relative to the superproject's origin, and this builds the same
    `(seed, fault)` at two different roots, at different depths, to hold that.
    """
    roots = [tmp_path / "first", tmp_path / "deeper" / "second-checkout-name"]
    shas: list[tuple[str, str, str, str]] = []

    for root in roots:
        root.mkdir(parents=True)
        monkeypatch.setattr(sandbox_module, "_SANDBOX_DIR", root)
        box = build_sandbox(SEED_BY_STATE["remove"], ["submodule_moved"])
        try:
            shas.append(_shas(box))
        finally:
            box.destroy()

    assert shas[0] == shas[1], (
        "the same (seed, fault) built at two absolute roots produced different SHAs, "
        "so something that depends on the path is entering the committed content"
    )


def test_the_root_carries_a_per_process_token(tmp_path, monkeypatch) -> None:
    """Two runs must not collide on one root; that is what blocked concurrency (#72).

    Checked as a pure function of the token rather than by building two sandboxes:
    the property is about the path, and building one to compare names would cost a
    sandbox per assertion. Varying the token is the stand-in for a second process.
    """
    monkeypatch.setattr(sandbox_module, "_SANDBOX_DIR", tmp_path)
    monkeypatch.setattr(sandbox_module, "_PROCESS_TOKEN", "first-process")
    one = sandbox_module._sandbox_root(0, ["diverged"])
    monkeypatch.setattr(sandbox_module, "_PROCESS_TOKEN", "second-process")
    two = sandbox_module._sandbox_root(0, ["diverged"])

    assert one != two, "two processes would share a sandbox root"
    assert one.parent == two.parent == tmp_path


@pytest.mark.parametrize(("state", "seed"), STATE_CASES)
def test_observe_does_not_mutate(state: str, seed: int, make_sandbox) -> None:
    box = make_sandbox(seed, ["submodule_moved"])
    before = StateFingerprint.observe(box)
    after = StateFingerprint.observe(box)
    assert before == after
    assert after.has_submodule_reference is True


def test_destroy_is_idempotent(make_sandbox) -> None:
    box = make_sandbox(SEED_BY_STATE["remove"], ["submodule_moved"])
    root = box.root
    assert root.exists()
    box.destroy()
    assert not root.exists()
    box.destroy()
