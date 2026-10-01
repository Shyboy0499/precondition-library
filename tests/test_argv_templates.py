"""The argv-template path runs allowlisted operations without a shell (issue #10).

A `steps` program is built into argv arrays and executed with `subprocess`
directly, so an attacker-controlled value is one element git receives verbatim
and cannot become code. These tests pin the three things that makes true: a
program declares exactly one executable representation, a path bound from
attacker-controlled `.gitmodules` is validated and contained before it reaches
argv, and a value carrying shell metacharacters is inert because nothing parses
it as shell.

The containment and inertness cases run against real sandboxes, because the
property is about what a real `git` does with a real repository.
"""

from __future__ import annotations

import pytest

from precondition_library.program import Predicate, Program, Provenance, Step
from precondition_library.runtime.probes import bindings
from precondition_library.runtime.templates import TEMPLATES, render, run_steps
from precondition_library.sandbox import create

_PROV = Provenance(
    compiled_from_task="argv-template test",
    model="none",
    compiler_version="test",
    episode_id="test",
    fault="none",
)
_PRE = [Predicate(name="p", description="d", probe="test -n {submodule_path}")]
_POST = [Predicate(name="q", description="d", probe="true")]


def _steps_program(*steps: Step) -> Program:
    return Program(
        id="t",
        intent="t",
        parameters=["submodule_path"],
        preconditions=_PRE,
        steps=list(steps),
        postconditions=_POST,
        provenance=_PROV,
    )


def test_a_program_declares_exactly_one_representation() -> None:
    common = dict(id="t", intent="t", preconditions=_PRE, postconditions=_POST, provenance=_PROV)
    with pytest.raises(ValueError, match="either body or steps"):
        Program(**common, body="git status", steps=[Step(template="fetch")])
    with pytest.raises(ValueError, match="must set a body or steps"):
        Program(**common)
    # One or the other validates.
    assert Program(**common, body="git status").steps is None
    assert Program(**common, steps=[Step(template="fetch")]).body is None


def test_every_catalogue_template_builds_a_git_argv() -> None:
    box = create(5, [])
    # A .gitmodules so submodule_path binds for the templates that need it.
    (box.work / ".gitmodules").write_text(
        '[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = ./x\n', encoding="utf-8"
    )
    try:
        for name, template in TEMPLATES.items():
            args = {"message": "chore: x"} if "message" in template.literals else {}
            argv = render(_steps_program(Step(template=name, args=args)), box)[0]
            assert argv[0] == "git", f"{name}: not a git argv"
            assert all(isinstance(part, str) for part in argv)
    finally:
        box.destroy()


def test_an_unknown_template_is_refused_before_anything_runs() -> None:
    box = create(5, [])
    try:
        ok, exit_code, _out, _err, _to, _unbound, reason, post = run_steps(
            _steps_program(Step(template="definitely-not-a-template")), box
        )
        assert not ok and exit_code == -1 and post is None
        assert "unknown template" in reason
    finally:
        box.destroy()


def test_a_gitmodules_path_that_escapes_the_tree_is_refused(make_sandbox) -> None:
    """`.gitmodules` is attacker-controlled, so an escaping path must not reach git."""
    box = create(5, [])
    (box.work / ".gitmodules").write_text(
        '[submodule "evil"]\n\tpath = ../../escape\n\turl = ./x\n', encoding="utf-8"
    )
    try:
        assert bindings(box)["submodule_path"] == "../../escape"
        ok, exit_code, _out, _err, _to, _unbound, reason, post = run_steps(
            _steps_program(Step(template="rm_cached_path")), box
        )
        assert not ok and exit_code == -1 and post is None
        assert "escapes the working tree" in reason
    finally:
        box.destroy()


def test_shell_metacharacters_in_a_path_are_inert() -> None:
    """A path carrying `$(...)` is contained (it stays under the tree) and runs as
    one argv element, so git treats it as a pathspec and the shell never sees it.
    """
    box = create(5, [])
    # A `>` redirect needs no whitespace, so it survives `.gitmodules`' reader and
    # would truncate `pwned` into existence *if* a shell ever parsed the path.
    hostile = "vendor/x>pwned"
    (box.work / ".gitmodules").write_text(
        f'[submodule "x"]\n\tpath = {hostile}\n\turl = ./x\n', encoding="utf-8"
    )
    try:
        argv = render(_steps_program(Step(template="rm_cached_path")), box)[0]
        assert argv[-1] == hostile, "the metacharacter string must be one argv element"
        # Running it: git rm fails on the nonexistent pathspec, but no shell parses
        # the `>`, so the redirect never happens.
        run_steps(_steps_program(Step(template="rm_cached_path")), box)
        assert not (box.work / "pwned").exists(), "a shell parsed the path; argv was not inert"
    finally:
        box.destroy()
