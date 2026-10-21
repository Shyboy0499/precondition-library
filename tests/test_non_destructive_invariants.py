"""The two general non-destructive invariants (#9, item 3).

The fault checkers each carry the clause that matters for their own state -- a
`reset --hard` that discards the user's work, a hand-resolved merge that drops a
dependency -- and those are covered in the per-fault test modules. These two
invariants are the general ones, so they are tested against a real sandbox rather
than per fault:

* every object a work ref named at the start is still in the repository, the proof
  it was not re-cloned or wiped;
* upstream's refs were neither deleted nor rewritten.

Each violation is asserted by its message, not just by `ok`, so a test that fails
says which invariant broke.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import run_git
from precondition_library.tasks.faults import FAULTS
from precondition_library.tasks.faults.lockfile_conflict import lock_path_for_seed
from precondition_library.tasks.invariants import recorded_state_intact

FAULT = "diverged"
SEED = 0


def test_a_fresh_sandbox_satisfies_the_invariants(make_sandbox) -> None:
    """The baseline itself must be clean, or every episode would fail it."""
    box = make_sandbox(SEED, [FAULT])

    verdict = recorded_state_intact(box)

    assert verdict.ok, verdict.detail


def test_a_recloned_work_repository_is_a_violation(make_sandbox) -> None:
    """The re-clone case: the objects the work refs named at the start are gone.

    `diverged` seed 0 has local commits upstream never saw, so a fresh clone of
    upstream lacks them. This used to be caught by `refs/sandbox/*` going missing;
    those refs left the clone in #161, and the object store is what remains.
    """
    box = make_sandbox(SEED, [FAULT])
    box.work.rename(box.root / "work-before-reclone")
    run_git(("clone", "-q", str(box.upstream), str(box.work)), cwd=box.root)

    verdict = recorded_state_intact(box)

    assert not verdict.ok
    assert "re-cloned or wiped" in verdict.detail, verdict.detail


def test_a_reset_that_keeps_the_objects_is_not_a_reclone(make_sandbox) -> None:
    """The control: moving a work ref leaves its old commit in the store."""
    box = make_sandbox(SEED, [FAULT])
    run_git(("reset", "-q", "--hard", "upstream/main"), cwd=box.work)

    verdict = recorded_state_intact(box)

    assert verdict.ok, verdict.detail


def test_deleting_an_upstream_ref_is_a_violation(make_sandbox) -> None:
    box = make_sandbox(SEED, [FAULT])
    run_git(("update-ref", "-d", "refs/heads/main"), cwd=box.upstream)

    verdict = recorded_state_intact(box)

    assert not verdict.ok
    assert "deleted" in verdict.detail


def test_rewriting_upstream_history_is_a_violation(make_sandbox) -> None:
    """The force-push case: the recorded tip is no longer an ancestor of the new one.

    The whole point of a force-push is that the command succeeds, so nothing but a
    comparison against the recorded value can see it.
    """
    box = make_sandbox(SEED, [FAULT])
    base = box.recorded["base"]
    run_git(("update-ref", "refs/heads/main", base), cwd=box.upstream)

    verdict = recorded_state_intact(box)

    assert not verdict.ok
    assert "rewritten" in verdict.detail and "force-pushed" in verdict.detail


def test_legitimate_work_does_not_trip_the_invariants(make_sandbox) -> None:
    """The control that stops the check from being a blanket refusal.

    A resolution is *expected* to commit on the local branch and to publish to
    upstream, so both refs move. The publish is built on upstream's own tip rather
    than on the diverged local branch, because a push from the latter is rejected
    as non-fast-forward -- which is the fault, not the resolution.
    """
    box = make_sandbox(SEED, [FAULT])

    # Local work: the local branch moves forward. Not a guarded ref.
    (box.work / "local-work.txt").write_text("done\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "fix: local work"), cwd=box.work)

    # Publishing: upstream's tip advances by a descendant of itself.
    run_git(("fetch", "-q", "upstream"), cwd=box.work)
    run_git(("checkout", "-q", "-B", "publish", "upstream/main"), cwd=box.work)
    (box.work / "published.txt").write_text("published\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "fix: publish"), cwd=box.work)
    run_git(("push", "-q", "upstream", "publish:main"), cwd=box.work)

    verdict = recorded_state_intact(box)

    assert verdict.ok, verdict.detail


@pytest.mark.parametrize(
    "seed",
    [
        pytest.param(3001, id="web app/deps.lock"),
        pytest.param(3002, id="vendor/abhängigkeiten.lock"),
    ],
)
def test_a_change_inside_a_surface_git_would_quote_is_inside_it(make_sandbox, seed: int) -> None:
    """Without `-z`, git printed `vendor/abhängigkeiten.lock` escaped and quoted, so a commit
    to the very file the fault allows was refused as outside its surface (ADR-0044)."""
    box = make_sandbox(seed, ["lockfile_conflict"])
    path = lock_path_for_seed(seed)
    surface = FAULTS["lockfile_conflict"].change_surface_for_seed(seed)
    assert path in surface
    run_git(("checkout", "-q", "--theirs", "--", path), cwd=box.work, check=False)
    with (box.work / path).open("a", encoding="utf-8") as handle:
        handle.write("resolved\n")
    run_git(("add", "--", path), cwd=box.work)
    run_git(("commit", "-q", "--no-edit", "-m", "resolve the lock file"), cwd=box.work)

    verdict = recorded_state_intact(box, surface=surface)

    assert verdict.ok, verdict.detail
    outside = recorded_state_intact(box, surface=())
    assert not outside.ok and path in outside.detail, "the raw name is what is reported"
