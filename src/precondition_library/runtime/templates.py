"""A fixed allowlist of argv templates, executed without a shell (issue #10).

A free-form shell body is the project's widest injection surface: the compile
step reads attacker-controlled repository text and authors a string that a shell
later interprets, so a commit message, a branch name or a `.gitmodules` path
that carries shell metacharacters can become code. This module is the safe
alternative the issue asks for. A program may carry `steps` instead of a `body`:
each step names one template from a fixed catalogue, and the executor builds an
**argv array** from the sandbox's bound values and the step's literals and runs
it directly -- `subprocess` with a list, never `bash -c`, never an f-string into
a shell. A hostile value is then one argv element git receives verbatim; it
cannot start a new command, redirect, or expand, because nothing parses it as
shell.

Two further checks ride on that:

* **Per-parameter validation.** Each bound name is validated before it reaches
  argv -- refs against a conservative charset, paths against a charset *and*
  realpath containment under the working tree. `submodule_path` is the one that
  matters: it is read from `.gitmodules`, which an attacker writes, so a path
  like `../../etc/x` is refused here rather than handed to `git -- <path>`.
* **A closed catalogue.** The templates are exactly the git operations the task
  family's resolutions need (sync: fetch/reset/rebase/merge; submodule:
  update/checkout/rm/config/add/commit). A resolution selects from them; it
  cannot invent an operation, so there is no template for `curl`, for a
  force-push, or for a write outside the tree.

This is the *executor* half of #10's argv-template item. The compile step still
emits shell bodies for the online arms (that migration is issue #4's territory);
the gold resolutions are expressed as `steps` and run through here, so the
catalogue is exercised end to end against real faulted sandboxes rather than
left as a representation with no user.

Imports only the standard library and provider-free runtime helpers, so
`runtime` still cannot reach the provider (the replay-isolation invariant).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ..program import GroundTruthResult, Program
from ..sandbox import Sandbox, run_env
from .confine import run_confined
from .probes import bindings, evaluate_predicates


class TemplateError(ValueError):
    """A step could not be turned into a safe argv: unknown template, missing or
    invalid argument, or a bound value that failed validation or containment.

    Raised while *building* the command, before anything runs, so a bad step is a
    refusal and not a half-executed body."""


_REF = re.compile(r"\A[A-Za-z0-9._][A-Za-z0-9._/\-]*\Z")
"""A git remote or branch name. Conservative: the sandbox binds `upstream` and
`main`, and a name with a space, a `..`, a shell metacharacter or a leading dash
is refused rather than reasoned about."""

_MAX_MESSAGE = 200


def _validate_ref(value: str, *, env: Sandbox) -> str:
    if not _REF.match(value) or ".." in value:
        raise TemplateError(f"not a valid ref component: {value!r}")
    return value


def _validate_path(value: str, *, env: Sandbox) -> str:
    """A repository-relative path that must stay inside the working tree.

    Containment is by realpath, so a `..` ladder, an absolute path, or a symlink
    that points out are all caught: the resolved target must be the working tree
    or sit under it. This is the check that makes an attacker-authored
    `.gitmodules` path safe to pass to `git -- <path>`.
    """
    if not value or "\x00" in value or "\n" in value:
        raise TemplateError(f"not a valid path: {value!r}")
    root = os.path.realpath(env.work)
    target = os.path.realpath(os.path.join(env.work, value))
    if target != root and not target.startswith(root + os.sep):
        raise TemplateError(f"path escapes the working tree: {value!r}")
    return value


def _validate_message(value: str, *, env: Sandbox) -> str:
    """A commit message literal the resolution authors.

    It rides into argv as one element, so its content cannot be code whatever it
    is; the bound is only to keep a pathological value out of the log, not a
    safety barrier (the argv array is)."""
    if "\x00" in value or len(value) > _MAX_MESSAGE:
        raise TemplateError(f"commit message is empty-byte or over {_MAX_MESSAGE} chars")
    return value


_PARAM_VALIDATORS: dict[str, Callable[..., str]] = {
    "upstream_remote": _validate_ref,
    "upstream_branch": _validate_ref,
    "submodule_path": _validate_path,
}
"""How each bound parameter is validated before it may enter an argv.

A parameter with no entry here is not accepted by any template that uses it; the
set is exactly the names the catalogue binds, so adding a template that needs a
new kind of value forces a decision about how to validate it rather than letting
it through unchecked.
"""


@dataclass(frozen=True)
class Template:
    """One allowlisted operation: the bound params it reads, the literals it
    takes, and how it assembles an argv from them.

    `build` receives only validated values. `ok_exits` names the exit codes that
    count as success -- a single tuple per template rather than shell's `|| true`,
    so "this failure is expected" is declared, not hidden in a body.
    """

    params: frozenset[str]
    literals: frozenset[str]
    build: Callable[[Mapping[str, str], Mapping[str, str]], list[str]]
    ok_exits: tuple[int, ...] = (0,)
    describes: str = ""


def _ref(bound: Mapping[str, str]) -> str:
    return f"{bound['upstream_remote']}/{bound['upstream_branch']}"


TEMPLATES: dict[str, Template] = {
    "fetch": Template(
        params=frozenset({"upstream_remote"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "fetch", bound["upstream_remote"]],
        describes="fetch from the upstream remote",
    ),
    "reset_hard_to_upstream": Template(
        params=frozenset({"upstream_remote", "upstream_branch"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "reset", "--hard", _ref(bound)],
        describes="reset the branch to upstream, discarding local commits",
    ),
    "rebase_onto_upstream": Template(
        params=frozenset({"upstream_remote", "upstream_branch"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "rebase", _ref(bound)],
        describes="replay local commits onto upstream",
    ),
    "merge_upstream_no_edit": Template(
        params=frozenset({"upstream_remote", "upstream_branch"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "merge", "--no-edit", _ref(bound)],
        describes="merge upstream into the local branch",
    ),
    "submodule_update_init": Template(
        params=frozenset({"submodule_path"}),
        literals=frozenset(),
        build=lambda bound, lit: [
            "git",
            "submodule",
            "update",
            "--init",
            "--",
            bound["submodule_path"],
        ],
        describes="initialise the nested checkout",
    ),
    "checkout_upstream_path": Template(
        params=frozenset({"upstream_remote", "upstream_branch", "submodule_path"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "checkout", _ref(bound), "--", bound["submodule_path"]],
        describes="take one path from upstream's tree",
    ),
    "rm_cached_path": Template(
        params=frozenset({"submodule_path"}),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "rm", "--cached", "--", bound["submodule_path"]],
        describes="unstage a path, keeping the working copy",
    ),
    "gitmodules_remove_section": Template(
        params=frozenset({"submodule_path"}),
        literals=frozenset(),
        build=lambda bound, lit: [
            "git",
            "config",
            "--file",
            ".gitmodules",
            "--remove-section",
            f"submodule.{bound['submodule_path']}",
        ],
        describes="drop the submodule's .gitmodules section",
    ),
    "add_gitmodules": Template(
        params=frozenset(),
        literals=frozenset(),
        build=lambda bound, lit: ["git", "add", "--", ".gitmodules"],
        describes="stage the edited .gitmodules",
    ),
    "commit": Template(
        params=frozenset(),
        literals=frozenset({"message"}),
        build=lambda bound, lit: ["git", "commit", "-q", "-m", lit["message"]],
        describes="commit the staged change with a fixed message",
    ),
}
"""The closed set of operations a `steps` program may run. Exactly the task
family's resolutions need; nothing writes outside the tree or reaches the
network, because no template does."""


@dataclass(frozen=True)
class StepPlan:
    """A built, validated step: the template id and its concrete argv."""

    template: str
    argv: list[str]
    ok_exits: tuple[int, ...]


@dataclass(frozen=True)
class _BuildOutcome:
    plans: list[StepPlan] = field(default_factory=list)
    error: str | None = None
    unbound: bool = False


def step_parameters(program: Program) -> set[str]:
    """Every bound parameter name the program's steps read.

    Used by admission's declaration check (#77): a step parameter that no
    precondition names is a program that has not said what it needs, the same
    defect the shell path checks for with `placeholders(body)`.
    """
    used: set[str] = set()
    for step in program.steps or []:
        template = TEMPLATES.get(step.template)
        if template is not None:
            used |= template.params
    return used


def _build_plans(program: Program, env: Sandbox) -> _BuildOutcome:
    bound = bindings(env)
    plans: list[StepPlan] = []
    for step in program.steps or []:
        template = TEMPLATES.get(step.template)
        if template is None:
            return _BuildOutcome(error=f"unknown template {step.template!r}")
        resolved: dict[str, str] = {}
        for name in template.params:
            if name not in bound:
                # A declared-but-unbindable parameter (e.g. submodule_path on a
                # repository with none): the step is inapplicable here, which is a
                # mis-fire to record, not a crash -- the same shape the shell path
                # gives an unbound body parameter (issue #76).
                return _BuildOutcome(error=f"{step.template}: cannot bind {{{name}}}", unbound=True)
            try:
                resolved[name] = _PARAM_VALIDATORS[name](bound[name], env=env)
            except TemplateError as exc:
                return _BuildOutcome(error=f"{step.template}: {exc}")
        literals: dict[str, str] = {}
        missing = template.literals - set(step.args)
        if missing:
            return _BuildOutcome(error=f"{step.template}: missing {sorted(missing)}")
        extra = set(step.args) - template.literals
        if extra:
            return _BuildOutcome(error=f"{step.template}: unexpected {sorted(extra)}")
        for name in template.literals:
            try:
                literals[name] = _LITERAL_VALIDATORS[name](step.args[name], env=env)
            except TemplateError as exc:
                return _BuildOutcome(error=f"{step.template}: {exc}")
        plans.append(StepPlan(step.template, template.build(resolved, literals), template.ok_exits))
    return _BuildOutcome(plans=plans)


_LITERAL_VALIDATORS: dict[str, Callable[..., str]] = {"message": _validate_message}


def run_steps(
    program: Program,
    env: Sandbox,
    *,
    timeout_s: float = 60.0,
) -> tuple[bool, int, str, str, bool, bool, str, GroundTruthResult | None]:
    """Execute a program's steps as argv arrays, then check postconditions.

    Returns the pieces `replay` folds into a `ReplayResult`: ok, exit_code,
    stdout, stderr, timed_out, unbound_parameter, reason, postconditions. Each
    step is built and validated first; a build error returns before anything
    runs. Steps run in order under `timeout_s` (shared across the sequence); the
    first step whose exit code is not in its `ok_exits` stops the sequence.
    Postconditions are checked whenever at least one step ran, so a late failure
    still leaves the evidence demotion needs.
    """
    outcome = _build_plans(program, env)
    if outcome.error is not None:
        # Nothing ran: a validation/containment refusal or an unbindable
        # parameter. `exit_code=-1`, postconditions left None, like the shell
        # path's refusal and unbound-parameter cases.
        return (False, -1, "", "", False, outcome.unbound, outcome.error, None)

    environment = run_env(env)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = 0
    timed_out = False
    failed_step: str | None = None
    for plan in outcome.plans:
        confined = run_confined(plan.argv, cwd=env.work, env=environment, timeout_s=timeout_s)
        stdout_parts.append(confined.stdout)
        stderr_parts.append(confined.stderr)
        if confined.timed_out:
            timed_out = True
            exit_code = -1
            failed_step = plan.template
            break
        exit_code = confined.returncode if confined.returncode is not None else -1
        if exit_code not in plan.ok_exits:
            failed_step = plan.template
            break

    postconditions = evaluate_predicates(program.postconditions, env, kind="postcondition")
    if timed_out:
        reason = f"step {failed_step!r} exceeded the {timeout_s:g}s timeout and was killed"
    elif failed_step is not None:
        reason = f"step {failed_step!r} exited {exit_code}"
    elif not postconditions.ok:
        reason = f"postconditions failed: {postconditions.detail}"
    else:
        reason = ""
    ok = failed_step is None and not timed_out and postconditions.ok
    return (
        ok,
        exit_code,
        "".join(stdout_parts),
        "".join(stderr_parts),
        timed_out,
        False,
        reason,
        postconditions,
    )


def render(program: Program, env: Sandbox) -> list[Sequence[str]]:
    """The argv each step would run, for tests and inspection. Raises on a bad step."""
    outcome = _build_plans(program, env)
    if outcome.error is not None:
        raise TemplateError(outcome.error)
    return [plan.argv for plan in outcome.plans]
