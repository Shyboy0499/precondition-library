"""Executing a Program against an environment, with zero LLM calls.

INVARIANT — this module must not import `precondition_library.provider`,
directly or transitively. The project's central claim is that a replay costs no
tokens, so the cheapest way to make the claim false is an import that quietly
reintroduces a model call. tests/test_replay_isolated_from_provider.py walks
the import graph under `src/` and fails if provider becomes reachable from here.
That test is the guardrail; this docstring is just the explanation.

Replay also never trusts the program it runs. The body is screened by the
effect guard, executes under a timeout inside a throwaway sandbox, and its
postconditions are re-checked afterwards rather than taken on faith. The
postcondition check is **unconditional once the body has run** — including when
it exited non-zero or was killed by the timeout — because that evidence is what
the failure policy demotes a program on. A replay that reported success because
the body's own exit code was zero would be measuring the wrong thing.
"""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from ..program import GroundTruthResult, Program
from ..sandbox import Sandbox, git_env
from .guard import Verdict, screen
from .probes import SHELL, evaluate_predicate, substitute


class ReplayResult(BaseModel):
    """What happened when a stored program ran."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    postconditions: GroundTruthResult | None = None
    """Populated whenever the body ran, even on failure — the evidence for demotion."""
    refused: bool = False
    """The guard refused the body, so nothing executed."""
    reason: str = ""
    """Why `ok` is false: a refusal, a timeout, a non-zero exit, or failed
    postconditions. Empty when `ok`."""


def _text(value: str | bytes | None) -> str:
    """The partial output a killed process left behind, as text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _bindings(env: Sandbox) -> dict[str, str]:
    """Values the sandbox supplies for the parameter names gold programs declare.

    `sandbox.create` clones its only remote as `upstream` and seeds the branch
    `main`, and the working clone is `env.work`. A program that declares a
    parameter this mapping cannot bind is not replayable: the placeholder would
    survive into the command text, and `substitute` raises rather than running a
    different question. The binding is the sandbox's fixed vocabulary, not a
    general mechanism; a fault that renamed the branch would need it derived
    from the sandbox, which this runtime does not yet do.
    """
    return {
        "work_dir": str(env.work),
        "upstream_remote": "upstream",
        "upstream_branch": "main",
    }


def check_postconditions(program: Program, env: Sandbox) -> GroundTruthResult:
    """Run the program's own postconditions. No model."""
    parameters = _bindings(env)
    predicates = [
        evaluate_predicate(predicate, env, parameters) for predicate in program.postconditions
    ]
    failed = [result for result in predicates if not result.ok]
    detail = (
        "; ".join(f"{result.name}: {result.observed}" for result in failed)
        if failed
        else f"all {len(predicates)} postcondition(s) held"
    )
    return GroundTruthResult(ok=not failed, detail=detail, predicates=predicates)


def replay(program: Program, env: Sandbox, *, timeout_s: float = 60.0) -> ReplayResult:
    """Run `program` in `env` under guard screening. Never calls a model.

    A guard refusal returns immediately with `refused=True` and executes nothing,
    including no postconditions. Otherwise the body runs in the sandbox's working
    directory under `timeout_s`; on expiry it is killed and `timed_out` is set
    rather than folded into a generic failure. Postconditions are then checked
    whatever the exit status was, and `ok` requires all three: the body exited
    zero, it did not time out, and every postcondition held.
    """
    decision = screen(program.body, env_root=str(env.work))
    if decision.verdict is Verdict.REFUSE:
        return ReplayResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr="",
            refused=True,
            reason=f"guard {decision.reason}",
        )

    body = substitute(program.body, _bindings(env))
    run_env = git_env()
    # Structural mitigation from the safety spec: `~` resolves inside the
    # sandbox, so a credential read through `~` lands on nothing. The guard
    # still screens explicit paths; this only makes one class of miss harmless.
    run_env["HOME"] = str(env.root)

    timed_out = False
    try:
        completed = subprocess.run(
            [*SHELL, body],
            cwd=env.work,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=timeout_s,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as expired:
        timed_out = True
        exit_code = -1
        stdout = _text(expired.stdout)
        stderr = _text(expired.stderr)

    # Unconditional: the body ran, so its result is evidence even if it failed.
    postconditions = check_postconditions(program, env)

    if timed_out:
        reason = f"body exceeded the {timeout_s:g}s timeout and was killed"
    elif exit_code != 0:
        reason = f"body exited {exit_code}"
    elif not postconditions.ok:
        reason = f"postconditions failed: {postconditions.detail}"
    else:
        reason = ""
    return ReplayResult(
        ok=not timed_out and exit_code == 0 and postconditions.ok,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        postconditions=postconditions,
        reason=reason,
    )
