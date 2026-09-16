"""Evaluating a Predicate against a sandbox.

A `Predicate` is a shell probe plus a name and an expectation. This module is the
single place that turns one into a `PredicateResult`: `replay` uses it for
postconditions, and admission and arm 3's dispatch use it for preconditions. It
lives on its own rather than inside `replay` because admission and dispatch must
agree exactly on what "the probe held" means, and two copies would eventually
disagree.

`bindings` also lives here despite once living in `replay`: a body and a probe are
substituted from the same fixed sandbox vocabulary, and a replay that bound
`{upstream}` differently from dispatch would make the ablation measure the
disagreement between two definitions rather than the two matchers.

Substitution is deliberately minimal -- `{name}` is replaced with the bound
value and nothing else about the string is interpreted, because a probe is a
shell command and the shell, not this module, owns its syntax. A placeholder
with no binding raises rather than becoming an empty string: an empty value
turns the probe into a different question (often one that silently holds), and a
wrong answer that looks right is the failure this project exists to measure.

The raise is split in two, because two different defects look alike from here.
A name outside `VOCABULARY` is a defect *in the program* -- a typo'd parameter
would otherwise never bind and the program would silently never fire -- so it
raises and admission records the rejection. A declared name that this environment
cannot bind (a program needing `submodule_path` on a repository with no
submodule) is not a crash: it is a precondition that does not hold, so
`evaluate_predicate` returns a failed `PredicateResult` naming why and dispatch
moves on. Collapsing the two would either abort a dispatch on an ordinary
non-match or let a typo'd program ship.

Probes run under `bash -c`, not `/bin/sh`. The gold probes use process
substitution (`comm -12 <(...)`), which is a bash extension and not POSIX; a
POSIX-only runner would make a correct probe report a false negative on Linux.
"""

from __future__ import annotations

import re
import subprocess

from ..program import GroundTruthResult, Predicate, PredicateResult, Program
from ..sandbox import Sandbox, git_env, submodule_path

VOCABULARY: frozenset[str] = frozenset(
    {"work_dir", "upstream_remote", "upstream_branch", "submodule_path"}
)
"""Every parameter name the runtime can bind, whether or not this environment can.

The set is fixed rather than derived from `bindings(env)` on purpose: a name
*outside* it is a compile defect and must raise, while a name inside it whose
value this particular sandbox cannot supply is an inapplicable precondition. The
two cases are indistinguishable from the bindings dict alone.
"""


class UnboundParameterError(KeyError):
    """A declared parameter that this environment cannot supply a value for.

    Subclasses `KeyError` because it is still a missing lookup: existing callers
    that treat an unbound placeholder in a *body* as a compile defect keep doing
    so. Preconditions are the case that must not raise, and
    `evaluate_predicate` catches this class before it escapes.
    """


# A `{name}` placeholder, but not `${name}`: the latter is a shell variable
# expansion and belongs to the shell, not to us. Minimal on purpose -- this is
# not a templating engine, and `{a,b}` / `{print $1}` must pass through intact.
_PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_]*)\}")

SHELL: tuple[str, ...] = ("bash", "-c")
"""The interpreter probes and bodies run under. See the module docstring."""

_MAX_EXCERPT = 160


def substitute(text: str, parameters: dict[str, str]) -> str:
    """Replace `{name}` placeholders in `text` from `parameters`.

    A name outside `VOCABULARY` raises `KeyError` -- an unknown placeholder is a
    defect in the program, and running the probe with the literal braces would
    ask a different (often falsely-holding) question. A declared name that this
    environment cannot bind raises `UnboundParameterError`, which callers that
    evaluate preconditions turn into a failed result rather than a crash.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in parameters:
            return parameters[name]
        if name in VOCABULARY:
            raise UnboundParameterError(
                f"the environment cannot bind {name!r}; a precondition that needs it "
                f"does not hold here, while an unknown name would be a program defect"
            )
        raise KeyError(
            f"no value bound for placeholder {name!r}; substituting an empty "
            f"string would ask a different question"
        )

    return _PLACEHOLDER.sub(replace, text)


def _excerpt(text: str) -> str:
    """A one-line, length-bounded view of a probe's output for `observed`."""
    return " ".join(text.split())[:_MAX_EXCERPT]


def evaluate_predicate(
    predicate: Predicate,
    env: Sandbox,
    parameters: dict[str, str],
    *,
    timeout_s: float = 30.0,
) -> PredicateResult:
    """Run one probe in `env` and report whether it held.

    `observed` always carries the exit code; when `expect_pattern` is set it also
    says whether the pattern matched and shows what stdout the match saw, and on
    a bare failure it carries a short stdout/stderr excerpt. It stays short
    because it lands in a record next to the ledger.

    A predicate naming a declared parameter this environment cannot bind is
    reported as a failed result, not raised: the precondition simply does not
    hold on this sandbox, which is the ordinary non-match dispatch and admission's
    negative side must see. A name outside the vocabulary still raises.
    """
    try:
        probe = substitute(predicate.probe, parameters)
    except UnboundParameterError as exc:
        return PredicateResult(name=predicate.name, ok=False, observed=f"not applicable: {exc}")
    try:
        completed = subprocess.run(
            [*SHELL, probe],
            cwd=env.work,
            capture_output=True,
            text=True,
            env=git_env(),
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return PredicateResult(
            name=predicate.name,
            ok=False,
            observed=f"timed out after {timeout_s:g}s",
        )

    ok = completed.returncode == predicate.expect_exit
    observed = f"exit={completed.returncode} (expected {predicate.expect_exit})"
    if predicate.expect_pattern is not None:
        matched = re.search(predicate.expect_pattern, completed.stdout) is not None
        ok = ok and matched
        verdict = "matched" if matched else "did not match"
        observed += f"; pattern {verdict} in stdout={_excerpt(completed.stdout)!r}"
    elif not ok:
        observed += f"; stdout={_excerpt(completed.stdout)!r} stderr={_excerpt(completed.stderr)!r}"
    return PredicateResult(name=predicate.name, ok=ok, observed=observed)


def bindings(env: Sandbox) -> dict[str, str]:
    """Values the sandbox supplies for the declared parameter names.

    `sandbox.create` clones its only remote as `upstream` and seeds the branch
    `main`, and the working clone is `env.work`. `submodule_path` comes from
    `sandbox.submodule_path`, which prefers the path a fault injector recorded
    and falls back to the repository's own `.gitmodules`: a correct removal of
    the submodule deletes that entry, so the recorded value is what still names
    the path in the state a program needs to bind it. It is present only when one
    of the two supplies it, and deliberately absent (not empty) otherwise. An
    absent declared name is what `substitute` reports as `UnboundParameterError`,
    so a program that needs a submodule is inapplicable rather than broken on a
    repository that has none.

    The binding is the sandbox's fixed vocabulary, not a general mechanism; a
    fault that renamed the branch would need it derived from the sandbox, which
    this runtime does not yet do.

    Public and shared because a probe and a body are substituted from this one
    mapping. A second copy in a caller is how replay and dispatch would come to
    disagree about what `{upstream_branch}` means, which would show up in the
    ablation as a difference between the arms.
    """
    values = {
        "work_dir": str(env.work),
        "upstream_remote": "upstream",
        "upstream_branch": "main",
    }
    path = submodule_path(env.work)
    if path is not None:
        values["submodule_path"] = path
    return values


def evaluate_preconditions(
    program: Program,
    env: Sandbox,
    *,
    timeout_s: float = 30.0,
) -> GroundTruthResult:
    """Run every precondition of `program` against `env`. No model.

    This is arm 3's whole question and admission's negative side, asked through
    one function so the two cannot disagree about what "the preconditions held"
    means. Each `PredicateResult` is kept, so a rejection names the precondition
    that failed and what it observed instead of collapsing to a bool a mismatch
    policy cannot diagnose.

    Every predicate runs even after one has failed. Short-circuiting would save
    a subprocess that is already this cheap, and in exchange the `detail` would
    depend on the order the preconditions happen to be stored in.
    """
    parameters = bindings(env)
    predicates = [
        evaluate_predicate(predicate, env, parameters, timeout_s=timeout_s)
        for predicate in program.preconditions
    ]
    failed = [result for result in predicates if not result.ok]
    detail = (
        "; ".join(f"{result.name}: {result.observed}" for result in failed)
        if failed
        else f"all {len(predicates)} precondition(s) held"
    )
    return GroundTruthResult(ok=not failed, detail=detail, predicates=predicates)
