"""A predicate's `expect_pattern` means what the model wrote (fourth live smoke run).

Two compiled programs were refused by our matcher, not by their own behaviour:

* `expect_pattern: ^refs/heads/{upstream_branch}$` was matched with the braces literal,
  so a renamed-branch program that retracked correctly failed its own postcondition;
* `expect_pattern: '[^[:space:]]'` is a POSIX class, which Python's `re` reads as a set
  followed by a literal `]`, so it never matched `git status` output.

These tests pin `runtime.probes.pattern_for` and, on real sandboxes, both predicates.
"""

from __future__ import annotations

import re

import pytest

from precondition_library.program import Predicate
from precondition_library.runtime.probes import bindings, evaluate_predicate, pattern_for
from precondition_library.sandbox import run_git
from precondition_library.tasks.faults.branch_renamed import renamed_branch_for_seed

RENAMED_PLAIN = 0
"""The `branch_renamed` seed whose state is `plain` (tests/test_sandbox_branch_renamed.py)."""


def test_a_placeholder_is_bound_and_escaped() -> None:
    pattern = pattern_for("^refs/heads/{upstream_branch}$", {"upstream_branch": "a.b"})
    assert pattern == r"^refs/heads/a\.b$"
    assert re.search(pattern, "refs/heads/a.b\n")
    assert not re.search(pattern, "refs/heads/axb\n")


@pytest.mark.parametrize(
    ("written", "text", "found"),
    [
        ("[^[:space:]]", "D app.py\n", True),
        ("[^[:space:]]", "  \n\t\n", False),
        ("^[[:digit:]]+$", "12\n", True),
        ("^[[:upper:]][[:lower:]]+$", "Main\n", True),
        ("^[[:xdigit:]]{7}$", "4211847\n", True),
        ("^[[:alpha:]]+$", "main2\n", False),
        ("^[[:punct:]]$", "]\n", True),
    ],
)
def test_a_posix_class_means_its_characters(written: str, text: str, found: bool) -> None:
    assert bool(re.search(pattern_for(written, {}), text)) is found


def test_a_quantifier_and_a_plain_pattern_are_left_alone() -> None:
    assert pattern_for("^[0-9]{3}$", {"upstream_branch": "x"}) == "^[0-9]{3}$"
    assert pattern_for("^0$", {}) == "^0$"


def _predicate(probe: str, pattern: str) -> Predicate:
    return Predicate(name="p", description="d", probe=probe, expect_pattern=pattern)


def test_the_live_postcondition_holds_once_the_branch_is_retracked(make_sandbox) -> None:
    box = make_sandbox(RENAMED_PLAIN, ["branch_renamed"])
    tracks = _predicate("git config branch.main.merge", "^refs/heads/{upstream_branch}$")
    assert not evaluate_predicate(tracks, box, bindings(box)).ok, "still follows the old name"
    new_name = renamed_branch_for_seed(RENAMED_PLAIN)
    run_git(("branch", f"--set-upstream-to=upstream/{new_name}", "main"), cwd=box.work)
    result = evaluate_predicate(tracks, box, bindings(box))
    assert result.ok, result.observed


def test_the_live_wip_check_holds_on_a_dirty_tree(make_sandbox) -> None:
    box = make_sandbox(0, [])
    wip = _predicate("git status --porcelain --untracked-files=all", "[^[:space:]]")
    assert not evaluate_predicate(wip, box, bindings(box)).ok, "a clean tree has no WIP"
    (box.work / "notes.txt").write_text("draft\n", encoding="utf-8")
    result = evaluate_predicate(wip, box, bindings(box))
    assert result.ok, result.observed


def test_an_unbound_name_in_a_pattern_does_not_hold(make_sandbox) -> None:
    box = make_sandbox(0, [])
    needs_submodule = _predicate("git status", "{submodule_path}")
    result = evaluate_predicate(needs_submodule, box, bindings(box))
    assert not result.ok and result.observed.startswith("not applicable")
