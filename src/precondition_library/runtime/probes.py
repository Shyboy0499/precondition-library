"""Evaluating a Predicate against a sandbox.

A `Predicate` is a shell probe plus a name and an expectation. This module is the
single place that turns one into a `PredicateResult`: `replay` uses it for
postconditions today, and the dispatch arms will use it for preconditions later.
It lives on its own rather than inside `replay` because admission and dispatch
must agree exactly on what "the probe held" means, and two copies would
eventually disagree.

Substitution is deliberately minimal -- `{name}` is replaced with the bound
value and nothing else about the string is interpreted, because a probe is a
shell command and the shell, not this module, owns its syntax. A placeholder
with no binding raises rather than becoming an empty string: an empty value
turns the probe into a different question (often one that silently holds), and a
wrong answer that looks right is the failure this project exists to measure.

Probes run under `bash -c`, not `/bin/sh`. The gold probes use process
substitution (`comm -12 <(...)`), which is a bash extension and not POSIX; a
POSIX-only runner would make a correct probe report a false negative on Linux.
"""

from __future__ import annotations

import re
import subprocess

from ..program import Predicate, PredicateResult
from ..sandbox import Sandbox, git_env

# A `{name}` placeholder, but not `${name}`: the latter is a shell variable
# expansion and belongs to the shell, not to us. Minimal on purpose -- this is
# not a templating engine, and `{a,b}` / `{print $1}` must pass through intact.
_PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_]*)\}")

SHELL: tuple[str, ...] = ("bash", "-c")
"""The interpreter probes and bodies run under. See the module docstring."""

_MAX_EXCERPT = 160


def substitute(text: str, parameters: dict[str, str]) -> str:
    """Replace `{name}` placeholders in `text` from `parameters`.

    Raises `KeyError` when a placeholder has no bound value, rather than
    substituting an empty string.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return parameters[name]
        except KeyError:
            raise KeyError(
                f"no value bound for placeholder {name!r}; substituting an empty "
                f"string would ask a different question"
            ) from None

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
    """
    probe = substitute(predicate.probe, parameters)
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
