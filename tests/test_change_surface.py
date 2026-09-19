"""Each fault declares the paths a resolution may touch, and the invariant checks it (#96).

The declaration is per fault and **declared**, not derived from what the injector touched --
a repair that rewrites a generated file from its source legitimately writes a path the
injection did not name, and a derived surface would refuse it for being outside the fault.

Two properties are pinned here, and they are different questions:

* **Coverage** -- what the injector itself committed is inside the declared surface. A
  declaration that forgot a path fails its own gold resolution in the test below rather than
  in a benchmark run.
* **Firing** -- a committed change outside the surface is refused. A check that has never
  been seen to fire is not a check.
"""

from __future__ import annotations

import pytest

from precondition_library.sandbox import run_git
from precondition_library.tasks.faults import ALL, FAULTS
from precondition_library.tasks.invariants import recorded_state_intact


@pytest.mark.parametrize("fault", ALL)
def test_the_declared_surface_covers_what_the_injector_itself_committed(
    fault, make_sandbox
) -> None:
    """The injection is inside the declaration, or the declaration is wrong.

    Cheap and mechanical, and it catches the failure mode a per-fault declaration invites:
    someone adds a path to an injector and does not add it to the surface. Every fault that
    records a base is checked, so `submodule_moved` -- which recorded none until this change
    -- is covered too.
    """
    box = make_sandbox(0, [fault])
    base = box.recorded["base"]
    committed = set(run_git(("diff", "--name-only", base, "HEAD"), cwd=box.work).stdout.split())

    outside = sorted(committed - set(FAULTS[fault].change_surface))

    assert not outside, (
        f"{fault} commits {outside} but declares only "
        f"{sorted(FAULTS[fault].change_surface)}; a resolution that had to touch those would "
        f"be refused (issue #96)"
    )


def test_a_committed_change_outside_the_surface_is_refused(make_sandbox) -> None:
    """The check fires, which is the only thing that makes the other test meaningful."""
    box = make_sandbox(0, ["diverged"])
    surface = FAULTS["diverged"].change_surface
    assert recorded_state_intact(box, surface=surface).ok, "the injected state should be inside"

    # A resolution that repairs the fault *and* commits something else.
    (box.work / "unrelated.txt").write_text("not part of this fault\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: unrelated"), cwd=box.work)

    verdict = recorded_state_intact(box, surface=surface)

    assert not verdict.ok
    assert "unrelated.txt" in verdict.detail
    assert "outside the declared change surface" in verdict.detail


def test_a_committed_change_inside_the_surface_is_allowed(make_sandbox) -> None:
    """The control: an in-surface commit must not be refused, or the check is a blanket ban."""
    box = make_sandbox(0, ["diverged"])
    surface = FAULTS["diverged"].change_surface

    (box.work / "app.py").write_text("# resolved\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "fix: resolve"), cwd=box.work)

    verdict = recorded_state_intact(box, surface=surface)

    assert verdict.ok, verdict.detail


def test_an_empty_surface_refuses_any_commit(make_sandbox) -> None:
    """`branch_renamed` is a ref operation, so a commit is outside a fault that has no files.

    An empty declaration is not "no check": it is the strictest one, and it is why the default
    is empty rather than permissive -- a fault that forgets to declare fails here.
    """
    box = make_sandbox(0, ["branch_renamed"])
    assert FAULTS["branch_renamed"].change_surface == ()

    (box.work / "app.py").write_text("# unrelated commit\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: commit something"), cwd=box.work)

    verdict = recorded_state_intact(box, surface=())

    assert not verdict.ok
    assert "app.py" in verdict.detail


def test_an_undeclared_surface_checks_only_the_recorded_state(make_sandbox) -> None:
    """`None` means the caller declared nothing, and says so in the detail.

    A hand-built sandbox has no fault to declare one for. The harness always passes it, so this
    is the weaker check on a path that only tests take -- and it says which check it ran rather
    than reporting a pass that looks like the full one.
    """
    box = make_sandbox(0, ["diverged"])

    verdict = recorded_state_intact(box)

    assert verdict.ok
    assert "no change surface was declared" in verdict.detail
