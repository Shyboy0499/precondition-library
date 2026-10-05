"""A probe must only read: one that changes the sandbox is refused (issue #10).

The guard permits writes inside the sandbox because bodies need them, so before this a
precondition such as `git reset --hard` ran and corrupted the state every later probe and
the episode observed. `evaluate_predicate` now snapshots the sandbox around each probe;
a probe that changed it is reported as not holding, flagged `refused`, and names what it
changed. Admission treats a refused precondition as a defect rather than as a "no", so a
mutating probe cannot pass the negative side by rejecting everything.

Every case runs against a real sandbox, never a mock: the property is about what a
shell command does to a real repository.
"""

from __future__ import annotations

import pytest
from test_episode_runner import DISCARD_SEED, _discard_program

from precondition_library.agents.compile import admit
from precondition_library.program import Predicate
from precondition_library.runtime.probes import bindings, evaluate_predicate, evaluate_predicates


def _probe(command: str) -> Predicate:
    return Predicate(name="under-test", description="a probe under test", probe=command)


@pytest.mark.parametrize(
    ("command", "part"),
    [
        ("echo written > probe-wrote-this.txt", "working tree"),
        ("git branch probe-made-this", "refs"),
        ("git config probe.touched yes", "config"),
        ("git checkout -q -b probe-moved-head", "HEAD"),
        ("git rm -q --cached app.py", "index"),
    ],
)
def test_a_probe_that_changes_the_sandbox_is_refused(command: str, part: str, make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    result = evaluate_predicate(_probe(command), box, bindings(box))
    assert result.ok is False
    assert result.refused is True
    assert "changed the sandbox" in result.observed and part in result.observed


def test_a_guard_refusal_is_flagged_as_a_refusal(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    result = evaluate_predicate(_probe("curl -s http://example.invalid/x"), box, bindings(box))
    assert result.ok is False and result.refused is True


def test_reading_is_not_refused_even_when_git_refreshes_the_index(make_sandbox) -> None:
    """`git status` rewrites the index's stat cache; that is not a change to the state."""
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    for command in ("git status --porcelain", "git log --oneline -1", "test -f app.py"):
        result = evaluate_predicate(_probe(command), box, bindings(box))
        assert result.refused is False, f"{command!r} only reads, but was refused"
        assert result.ok is True


def test_refusals_are_counted_on_the_combined_verdict(make_sandbox) -> None:
    box = make_sandbox(DISCARD_SEED, ["diverged"])
    verdict = evaluate_predicates(
        [_probe("test -f app.py"), _probe("git branch probe-made-this")],
        box,
        kind="precondition",
    )
    assert verdict.ok is False
    assert verdict.refusals == 1


def test_admission_rejects_a_program_whose_precondition_writes() -> None:
    """A mutating probe reads as "no" everywhere; admission must not take that as a pass."""
    base = _discard_program()
    writes = Predicate(
        name="writes_a_branch",
        description="Creates a branch while checking.",
        probe="git branch probe-side-effect && true",
    )
    program = _discard_program(
        id="mutating-precondition", preconditions=[*base.preconditions, writes]
    )
    admitted, reason = admit(program, "diverged", seeds=[DISCARD_SEED])
    assert admitted is False
    assert "was refused" in reason and "changed the sandbox" in reason


def test_the_compile_prompt_states_the_rule() -> None:
    """The seventh live run's first program fetched with `--prune` in a precondition and
    was refused; the model is told the rule it is held to, and who fetches."""
    from precondition_library.agents.compile import SYSTEM_PROMPT

    assert "must only read" in SYSTEM_PROMPT
    assert "Fetching is the body's job" in SYSTEM_PROMPT
