"""A shell variable a body assigns itself is not an environment read (issue #180).

The third live run's compiled `submodule_moved` program was refused at admission for
`$a`, in a probe that set `a` one statement earlier:

    a=$(git rev-parse HEAD:{submodule_path}); b=$(...); test -n "$a" && ... "$a" != "$b"

The guard's environment-read rule matched any `$NAME`. It now lets through a variable
the body assigned in an earlier statement, and still refuses everything the rule exists
for: an unassigned variable, a read before the assignment (including `FOO=$FOO:x`), the
environment dumpers, and credential-looking names. Since #214 a `read` after a compound
keyword (`while read -r x`) or its own assignments (`IFS= read -r x`) assigns too, and so
does an assignment in a `case` arm or after `then`, `do` or `else`.
"""

from __future__ import annotations

import pytest

from precondition_library.program import Predicate, Program, ProgramStatus, Provenance
from precondition_library.runtime.guard import Verdict, screen
from precondition_library.runtime.probes import evaluate_preconditions
from precondition_library.tasks.faults import build_sandbox

ROOT = "/sandbox/root"

LIVE_CASE_ARM = (
    "f=notes/scratch.txt; dir=notes\n"
    'base=$(basename "$f")\n'
    'case "$base" in\n'
    "  *.*) name=${base%.*}; ext=.${base##*.} ;;\n"
    "  *)   name=$base; ext= ;;\n"
    "esac\n"
    'new="$dir/$name.local$ext"'
)
"""The fifth live run's compiled body, cut to the `case` that assigns `name` and `ext`. Its
`$name` was refused as an environment read: the assignment follows a case arm's `)`."""

LIVE_PROBE = (
    "a=$(git rev-parse HEAD:{submodule_path}); "
    "b=$(git rev-parse {upstream_remote}/{upstream_branch}:{submodule_path});\n"
    'test -n "$a" && test -n "$b" && test "$a" != "$b"'
)


@pytest.mark.parametrize(
    "body",
    [
        'a=$(git rev-parse HEAD); test -n "$a"',
        'a=1\ntest "$a" = 1',
        'export X=1; test "$X" = 1',
        'local n=3 && test "$n" -gt 1',
        'read -r head rest <<< "$(git rev-parse HEAD)"; test -n "$head"',
        'for f in a b; do test -n "$f"; done',
        'x=1; test "${x}" = 1',
        'git diff HEAD | while read -r line; do echo "$line" >> notes.txt; done',
        'while IFS= read -r pkg; do test -n "$pkg"; done < .git/lock-additions',
        'until read -r n; do :; done; test -n "$n"',
        'if read -r first < deps.lock; then test -n "$first"; fi',
        LIVE_CASE_ARM,
        'if true; then n=1; fi; test "$n" = 1',
        'while false; do x=1; done; echo "$x"',
        'if false; then :; else y=2; fi; test "$y" = 2',
    ],
)
def test_a_variable_the_body_assigned_first_is_allowed(body: str) -> None:
    decision = screen(body, env_root=ROOT)
    assert decision.verdict is Verdict.ALLOW, decision.reason


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ('test -n "$HOME"', "$HOME"),
        ('echo "$a"; a=1', "$a"),
        ("FOO=$FOO:x; echo done", "$FOO"),
        ('a=1 test "$b" = 1', "$b"),
        ("echo ${PATH}", "${PATH}"),
        ("while read -r x; do echo $PATH; done", "$PATH"),
        ('echo "$x"; while read -r x; do :; done', "$x"),
        ('case x in x) echo "$PATH";; esac', "$PATH"),
        ('echo "$name"; case x in x) name=1;; esac', "$name"),
    ],
)
def test_an_unassigned_or_early_read_is_still_refused(body: str, named: str) -> None:
    decision = screen(body, env_root=ROOT)
    assert decision.verdict is Verdict.REFUSE
    assert decision.reason == f"refused environment-variable read: {named}"


def test_credential_names_and_dumpers_stay_refused_even_when_assigned() -> None:
    assert screen('GITHUB_TOKEN=x; echo "$GITHUB_TOKEN"', env_root=ROOT).verdict is (
        Verdict.REFUSE
    ), "a credential-looking name is refused by the credential rule regardless"
    assert screen("a=1; printenv", env_root=ROOT).verdict is Verdict.REFUSE


def test_the_live_probe_now_evaluates_on_a_real_sandbox() -> None:
    """The probe #180 found, run as a precondition: evaluated, not refused."""
    program = Program(
        id="repin-under-test",
        intent="restore_submodule_state",
        variant="repin",
        parameters=["submodule_path", "upstream_remote", "upstream_branch"],
        preconditions=[
            Predicate(
                name="pin_differs",
                description="HEAD and upstream record different submodule commits",
                probe=LIVE_PROBE,
            )
        ],
        body="true\n",
        postconditions=[],
        provenance=Provenance(
            compiled_from_task="t",
            model="m",
            compiler_version="v",
            episode_id="e",
            fault="submodule_moved",
        ),
        status=ProgramStatus.CANDIDATE,
    )
    box = build_sandbox(1, ["submodule_moved"])  # seed 1 injects `repin`
    try:
        result = evaluate_preconditions(program, box)
    finally:
        box.destroy()
    (predicate,) = result.predicates
    assert not predicate.refused, predicate.observed
    assert result.ok, "on a repin state the pins differ, so the probe holds"
