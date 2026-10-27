"""The real-`Cargo.lock` fault (#306): each state conflicts, and different actions are right.

Requires `cargo` (it resolves from vendored crates, offline). GitHub's Ubuntu runners and the
development container have it; without it these tests fail rather than skip, so a missing
toolchain is seen.
"""

from __future__ import annotations

import pytest

from precondition_library.bench.lock_actions import three_way, unify
from precondition_library.sandbox import Sandbox, create, git_out, run_git
from precondition_library.tasks.faults import cargo_lock_conflict as fault
from precondition_library.tasks.invariants import record_refs_at_start, recorded_state_intact
from precondition_library.tasks.spec import GroundTruth

SEED_FOR = {
    state: next(s for s in range(50) if fault.state_for_seed(s) == state)
    for state in fault.INJECTED_STATES
}


def _build(seed: int) -> Sandbox:
    box = create(seed, [fault.SPEC.name])
    fault.SPEC.inject(seed, box)
    record_refs_at_start(box)
    return box


@pytest.fixture
def built():
    boxes: list[Sandbox] = []

    def build(state: str) -> Sandbox:
        boxes.append(_build(SEED_FOR[state]))
        return boxes[-1]

    yield build
    for box in boxes:
        box.destroy()


def _grade(box: Sandbox, state: str) -> GroundTruth:
    """Both of the episode's clauses, the recorded state first."""
    intact = recorded_state_intact(box, surface=fault.SPEC.change_surface_for_seed(SEED_FOR[state]))
    return intact if not intact.ok else fault.SPEC.check(box)


def _resolve(box: Sandbox, action: str) -> None:
    """Merge upstream, then settle `Cargo.lock` the way `action` does, and commit."""
    work = box.work
    run_git(("merge", "--no-edit", "upstream/main"), cwd=work, check=False)
    side = "--theirs" if "upstream" in action else "--ours"
    run_git(("checkout", side, "--", fault.LOCK), cwd=work)
    if action.startswith("reconcile"):
        fault.cargo(work, "update", "--workspace")
    if action == "local_then_update_alder":
        fault.cargo(work, "update", "-p", "alder")
    run_git(("add", "-A"), cwd=work)
    run_git(("commit", "-q", "--no-edit"), cwd=work)


ACTIONS = (
    "take_local",
    "take_upstream",
    "reconcile_local",
    "reconcile_upstream",
    "local_then_update_alder",
)
RIGHT = {
    "both_added": {"reconcile_local", "reconcile_upstream", "local_then_update_alder"},
    "local_removed": {"reconcile_upstream", "local_then_update_alder"},
    "same_crate_bumped": {"local_then_update_alder"},
}


def test_every_state_is_reachable() -> None:
    assert set(SEED_FOR) == set(fault.INJECTED_STATES)


@pytest.mark.parametrize("state", fault.INJECTED_STATES)
def test_the_sync_conflicts_in_the_lock_and_the_injected_state_fails(state: str, built) -> None:
    box = built(state)
    merged = run_git(
        ("merge-tree", "--write-tree", "--name-only", "-z", "upstream/main", "HEAD"),
        cwd=box.work,
        check=False,
    )
    assert merged.returncode == 1
    assert merged.stdout.split("\0\0", 1)[0].split("\0")[1:] == [fault.LOCK]
    assert not fault.SPEC.check(box).ok


@pytest.mark.parametrize("state", fault.INJECTED_STATES)
@pytest.mark.parametrize("action", ACTIONS)
def test_exactly_the_right_actions_pass(state: str, action: str, built) -> None:
    box = built(state)
    _resolve(box, action)
    verdict = _grade(box, state)
    assert verdict.ok == (action in RIGHT[state]), f"{state}/{action}: {verdict.detail}"


def test_a_lock_cargo_would_rewrite_is_refused_even_with_the_right_set(built) -> None:
    """The set alone is not enough. Drop `birch` from the manifest after a right resolution:
    the lock still resolves the expected set, and cargo refuses it for the manifest it is in."""
    box = built("both_added")
    _resolve(box, "reconcile_upstream")
    assert _grade(box, "both_added").ok
    manifest = box.work / fault.MANIFEST
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace('birch = "0.2"\n', ""), encoding="utf-8")
    run_git(("commit", "-q", "-am", "drop a dependency the lock still lists"), cwd=box.work)

    verdict = fault.SPEC.check(box)
    assert not verdict.ok
    assert "cargo refuses" in verdict.detail, verdict.detail


@pytest.mark.parametrize("state", fault.INJECTED_STATES)
def test_the_package_level_merge_is_right_except_where_a_removal_must_win(
    state: str, built
) -> None:
    """The expected sets against `bench.lock_actions`' three-way merge, unified: equal where the
    design says the package merge is right, and different where local removed what upstream
    bumped -- the merge keeps upstream's `birch`, which nothing requires any more."""
    box = built(state)

    def lock_at(revision: str) -> set[tuple[str, str]]:
        text = git_out("show", f"{revision}:{fault.LOCK}", cwd=box.work)
        return fault.packages_of(text)

    merged = unify(
        fault.LOCK,
        three_way(
            lock_at(box.recorded["base"]),
            lock_at(box.recorded["local-tip"]),
            lock_at("upstream/main"),
        ),
    )
    assert (merged == fault.EXPECTED[state]) == (state != "local_removed")


def test_the_same_seed_builds_the_same_commits() -> None:
    seed = SEED_FOR["same_crate_bumped"]
    first = _build(seed)
    try:
        tips = (git_out("rev-parse", "HEAD", cwd=first.work), first.recorded["local-tip"])
    finally:
        first.destroy()
    second = _build(seed)
    try:
        assert (git_out("rev-parse", "HEAD", cwd=second.work), second.recorded["local-tip"]) == tips
    finally:
        second.destroy()


# --- a body may call cargo, through homes inside the sandbox (ADR-0051) ----------------------


def test_a_confined_body_resolves_a_state_with_cargo(built) -> None:
    """The way a learned program runs: a shell body, confined, under `run_env` only."""
    from precondition_library.runtime.confine import run_confined
    from precondition_library.runtime.replay import SHELL
    from precondition_library.sandbox import run_env

    box = built("same_crate_bumped")
    body = (
        "git merge --no-edit upstream/main || true\n"
        "git checkout --ours -- Cargo.lock\n"
        "cargo update -p alder\n"
        "git add -A\n"
        "git commit -q --no-edit\n"
    )
    ran = run_confined([*SHELL, body], cwd=box.work, env=run_env(box), timeout_s=300)
    assert ran.returncode == 0, ran.stderr
    verdict = _grade(box, "same_crate_bumped")
    assert verdict.ok, verdict.detail


def test_the_cargo_variables_name_only_the_sandbox(built) -> None:
    from precondition_library.sandbox import run_env

    box = built("both_added")
    env = run_env(box)
    for name in ("RUSTUP_HOME", "CARGO_HOME"):
        assert env[name].startswith(str(box.root)), (name, env[name])
    assert env["CARGO_NET_OFFLINE"] == "true"


def test_a_sandbox_without_a_toolchain_gets_no_cargo_variables(tmp_path) -> None:
    from precondition_library.sandbox import run_env

    box = create(0, [])
    try:
        assert not {"RUSTUP_HOME", "CARGO_HOME", "RUSTUP_TOOLCHAIN"} & set(run_env(box))
    finally:
        box.destroy()


# --- the intent's rules agree with the checker (#306) ----------------------------------------

VARIANT_ACTION = {
    "keep_local_bumps": "keep_local_bumps",
    "reconcile_upstream_lock": "reconcile_upstream",
    "reconcile_local_lock": "reconcile_local",
}
"""Each variant, as the action that performs it."""


def _keep_local_bumps(box: Sandbox) -> None:
    """The generic form: the local lock, reconciled, then every crate only upstream moved."""
    from precondition_library.signatures import StateFingerprint

    moved = StateFingerprint.observe(box).lock_moved_upstream_only
    work = box.work
    run_git(("merge", "--no-edit", "upstream/main"), cwd=work, check=False)
    run_git(("checkout", "--ours", "--", fault.LOCK), cwd=work)
    fault.cargo(work, "update", "--workspace")
    for crate in moved:
        fault.cargo(work, "update", "-p", crate)
    run_git(("add", "-A"), cwd=work)
    run_git(("commit", "-q", "--no-edit"), cwd=work)


@pytest.mark.parametrize("state", fault.INJECTED_STATES)
def test_the_rules_label_each_state_as_declared(state: str, built) -> None:
    from precondition_library.signatures import StateFingerprint

    observed = StateFingerprint.observe(built(state))
    decided = fault.INTENT.correct_variant(observed)
    assert decided is not None and decided.id == fault.STATE_VARIANT[state]


@pytest.mark.parametrize("state", fault.INJECTED_STATES)
@pytest.mark.parametrize("variant", sorted(VARIANT_ACTION))
def test_a_variant_is_acceptable_exactly_where_its_action_passes(
    state: str, variant: str, built
) -> None:
    from precondition_library.signatures import StateFingerprint

    box = built(state)
    acceptable = variant in fault.INTENT.acceptable_variants(StateFingerprint.observe(box))
    if variant == "keep_local_bumps":
        _keep_local_bumps(box)
    else:
        _resolve(box, VARIANT_ACTION[variant])
    verdict = _grade(box, state)
    assert verdict.ok == acceptable, f"{state}/{variant}: {verdict.detail}"
