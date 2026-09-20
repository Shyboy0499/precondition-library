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

A third property was added later (issue #96): **the gold resolution itself** stays inside the
surface, per fault and per seed. The injector's coverage above is a different question -- it says
the declaration covers what the fault did, not what the repair legitimately needs to do. The gold
resolution is replayed for real, in a real sandbox, with the precondition filter arm 3 would apply,
because a resolution whose preconditions do not hold is one the dispatcher would never run and
asserting its surface would be asserting about a program that cannot fire.
"""

from __future__ import annotations

import pytest
from conftest import gold_programs

from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.runtime.replay import replay
from precondition_library.sandbox import run_git
from precondition_library.tasks.faults import ALL, FAULTS
from precondition_library.tasks.invariants import recorded_state_intact
from precondition_library.tasks.registry import ambiguous_intents

GOLD_SEEDS = (0, 1, 2, 3)
"""The seeds the gold resolutions are replayed on. Every seed's state has exactly one correct
resolution, so the precondition filter is what selects it -- see the test below."""

GOLD_CASES = [(intent.name, seed) for intent in ambiguous_intents() for seed in GOLD_SEEDS]


def _firing(intent_name: str, seed: int, make_sandbox):
    """The gold program whose preconditions hold in this state, with its live sandbox.

    Returns the sandbox too, because the caller has to keep working in it -- replaying,
    committing, and then asking the invariant. The caller owns destruction through the fixture.
    """
    programs = gold_programs(intent_name)
    fault = programs[0].provenance.fault
    box = make_sandbox(seed, [fault])
    firing = [program for program in programs if evaluate_preconditions(program, box).ok]
    return box, fault, firing


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


# --- the gold resolution, which is a different question from the injector (#96) ----


@pytest.mark.parametrize(
    ("intent_name", "seed"), GOLD_CASES, ids=[f"{i}-s{s}" for i, s in GOLD_CASES]
)
def test_the_gold_resolution_stays_inside_its_declared_surface(
    intent_name, seed, make_sandbox
) -> None:
    """The repair is inside the declaration, replayed for real in a real sandbox.

    This is the half the injector-coverage test cannot see. That test asks whether the declaration
    covers what the *fault* did; this one asks whether it covers what the *repair* legitimately
    has to do, which is the question a declaration can plausibly get wrong -- and getting it wrong
    refuses a correct resolution.

    The replay goes through `runtime.replay` rather than running the body's commands directly, so
    the guard screens it and the parameters are bound the way an episode binds them. Only programs
    whose preconditions hold are replayed, because that is the set arm 3 can dispatch to; asserting
    a surface for a program that cannot fire would be asserting about a program that never runs.
    """
    box, fault, firing = _firing(intent_name, seed, make_sandbox)

    assert len(firing) == 1, (
        f"{intent_name} seed {seed} has {len(firing)} correct gold resolutions "
        f"({[p.variant for p in firing]}); the state has one answer, so a gold set where two fire "
        f"or none does cannot score dispatch"
    )
    program = firing[0]
    base = box.recorded["base"]

    result = replay(program, box)

    assert not result.refused, result.reason
    assert not result.unbound_parameter, result.reason
    assert result.exit_code == 0, (result.stdout, result.stderr)

    committed = set(run_git(("diff", "--name-only", base, "HEAD"), cwd=box.work).stdout.split())
    assert committed, (
        "the gold resolution committed nothing, so the surface check has nothing to check; this "
        "test would pass on any declaration"
    )

    verdict = recorded_state_intact(box, surface=FAULTS[fault].change_surface)

    assert verdict.ok, verdict.detail
    assert committed <= set(FAULTS[fault].change_surface), (
        f"the gold resolution for {fault} touched {sorted(committed)}"
    )


def test_an_over_broad_resolution_is_refused(make_sandbox) -> None:
    """A resolution that repairs the fault *and* does more is the case the invariant exists for.

    Distinct from the firing test above, which commits collateral on top of the injected fault
    without repairing it. This one replays the real gold resolution first -- so the fault *is*
    repaired -- and then adds the collateral, which is the shape a genuinely over-broad repair
    takes: reaching the expected state while rewriting something the fault never touched.
    """
    box, fault, firing = _firing("sync_fork_with_upstream", 0, make_sandbox)
    assert len(firing) == 1
    surface = FAULTS[fault].change_surface
    assert replay(firing[0], box).exit_code == 0

    assert recorded_state_intact(box, surface=surface).ok, "the repair alone should be accepted"

    (box.work / "unrelated.txt").write_text("not part of this fault\n", encoding="utf-8")
    run_git(("add", "-A"), cwd=box.work)
    run_git(("commit", "-q", "-m", "chore: collateral"), cwd=box.work)

    verdict = recorded_state_intact(box, surface=surface)

    assert not verdict.ok
    assert "unrelated.txt" in verdict.detail
