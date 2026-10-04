"""`lockfile_conflict`'s three states, graded by its checker (#191, step 2).

Each seed selects `additions_only`, `upstream_removed` or `local_removed`. These tests
replay the fixed resolutions the design on #191 measured, on real sandboxes, and pin
which the checker accepts in which state:

* **take upstream**: merge, take upstream's file, re-insert the entries the local side
  added since the merge base;
* **keep local**: the mirror image;
* a **union merge**, which keeps both sides' lines -- and so both version lines;
* the fault is present after injection in every state, and observing it sees a
  conflicted `deps.lock` and which side dropped what.
"""

from __future__ import annotations

import subprocess

import pytest

from precondition_library.signatures import StateFingerprint
from precondition_library.tasks.faults.lockfile_conflict import (
    INJECTED_STATES,
    SPEC,
    removable_dependency_for_seed,
    state_for_seed,
)

SEED_FOR = {"additions_only": 0, "local_removed": 2, "upstream_removed": 5}

_ADDED = "git diff {a} {b} -- deps.lock | sed -n 's/^+    \"\\(.*\\)\",$/\\1/p'"
_INSERT = "sed -i '/^packages = \\[$/a\\    \"'\"$e\"'\",' deps.lock"


def _rebuild_from(side: str) -> str:
    """Merge, take `side`'s file, re-insert the other side's additions since the base."""
    theirs_or_ours, other = (
        ("--theirs", "HEAD") if side == "upstream" else ("--ours", "upstream/main")
    )
    return (
        "base=$(git merge-base HEAD upstream/main) && "
        f"added=$({_ADDED.format(a='$base', b=other)}) && "
        "{ git merge --no-edit upstream/main || true; } && "
        f"git checkout {theirs_or_ours} deps.lock && "
        f'printf "%s\\n" "$added" | while read -r e; do [ -n "$e" ] && {_INSERT}; done; '
        "git add deps.lock && git -c core.editor=true commit -q --no-edit"
    )


RESOLUTIONS = {
    "take_upstream": _rebuild_from("upstream"),
    "keep_local": _rebuild_from("local"),
    "union": "echo 'deps.lock merge=union' >> .git/info/attributes && "
    "git merge --no-edit upstream/main",
}

ACCEPTED = {
    "additions_only": {"take_upstream", "keep_local"},
    "upstream_removed": {"take_upstream"},
    "local_removed": {"keep_local"},
}


def test_the_seeds_cover_every_state() -> None:
    assert {state_for_seed(seed) for seed in SEED_FOR.values()} == set(INJECTED_STATES)
    assert all(state_for_seed(seed) == state for state, seed in SEED_FOR.items())


@pytest.mark.parametrize("state", INJECTED_STATES)
def test_each_state_is_the_fault_and_observed_as_declared(state: str, make_sandbox) -> None:
    seed = SEED_FOR[state]
    box = make_sandbox(seed, ["lockfile_conflict"])
    assert not SPEC.check(box).ok
    seen = StateFingerprint.observe(box)
    removed = f'    "{removable_dependency_for_seed(seed)}",'
    assert seen.merge_conflicted_files == ["deps.lock"]
    assert seen.upstream_dropped_lines == ([removed] if state == "upstream_removed" else [])
    assert seen.local_dropped_lines == ([removed] if state == "local_removed" else [])


@pytest.mark.parametrize(
    ("state", "resolution"),
    [(state, resolution) for state in INJECTED_STATES for resolution in RESOLUTIONS],
)
def test_the_checker_accepts_what_the_design_measured(
    state: str, resolution: str, make_sandbox
) -> None:
    box = make_sandbox(SEED_FOR[state], ["lockfile_conflict"])
    subprocess.run(["bash", "-c", RESOLUTIONS[resolution]], cwd=box.work, check=False)
    verdict = SPEC.check(box)
    assert verdict.ok == (resolution in ACCEPTED[state]), (state, resolution, verdict.detail)


def test_a_union_merge_is_refused_for_its_two_version_lines(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["additions_only"], ["lockfile_conflict"])
    subprocess.run(["bash", "-c", RESOLUTIONS["union"]], cwd=box.work, check=False)
    verdict = SPEC.check(box)
    assert not verdict.ok and "version lines" in verdict.detail


def test_resurrecting_a_removed_dependency_is_refused(make_sandbox) -> None:
    box = make_sandbox(SEED_FOR["upstream_removed"], ["lockfile_conflict"])
    subprocess.run(["bash", "-c", RESOLUTIONS["keep_local"]], cwd=box.work, check=False)
    verdict = SPEC.check(box)
    assert not verdict.ok and "removed is back" in verdict.detail
