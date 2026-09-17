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

A body whose declared placeholders this environment cannot bind never runs
(issue #76). That is a recorded `ReplayResult`, not an exception: the program
*fired*, so the episode is a mis-fire the metric counts and must survive to be
recorded, and an unhandled raise here ended a whole run. The raise is kept for
the other case — a placeholder outside the vocabulary is a compile defect, and
`admit` still refuses that program — because #77 depends on the two being
distinguishable.
"""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from ..program import GroundTruthResult, Program
from ..sandbox import Sandbox, git_env
from .guard import Verdict, screen
from .probes import SHELL, UnboundParameterError, bindings, evaluate_predicates, substitute


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
    unbound_parameter: bool = False
    """The body named a declared parameter this environment cannot bind, so the
    body never ran and there is no postcondition evidence (issue #76).

    Distinct from a body that ran and failed its postconditions, which sets
    `postconditions` to the failed result: here `postconditions` stays `None`
    because nothing executed. A name *outside* the vocabulary is a program
    defect and is not this case — `substitute` still raises for it."""
    reason: str = ""
    """Why `ok` is false: a refusal, an unbound body parameter, a timeout, a
    non-zero exit, or failed postconditions. Empty when `ok`."""


def _text(value: str | bytes | None) -> str:
    """The partial output a killed process left behind, as text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def check_postconditions(program: Program, env: Sandbox) -> GroundTruthResult:
    """Run the program's own postconditions. No model.

    Shares `evaluate_predicates` with `evaluate_preconditions` so a postcondition
    and a precondition are judged by the same rule. The 30s per-probe timeout is
    the helper's default: unlike the body's `timeout_s`, postconditions are not
    rebound here, which is the current behaviour rather than a decision.
    """
    return evaluate_predicates(program.postconditions, env, kind="postcondition")


def replay(program: Program, env: Sandbox, *, timeout_s: float = 60.0) -> ReplayResult:
    """Run `program` in `env` under guard screening. Never calls a model.

    A guard refusal returns immediately with `refused=True` and executes nothing,
    including no postconditions. Otherwise the body runs in the sandbox's working
    directory under `timeout_s`; on expiry it is killed and `timed_out` is set
    rather than folded into a generic failure. Postconditions are then checked
    whatever the exit status was, and `ok` requires all three: the body exited
    zero, it did not time out, and every postcondition held.

    A body that names a declared parameter this environment cannot bind returns
    `unbound_parameter=True` instead of raising (issue #76); a placeholder
    outside the vocabulary still raises, because that is a compile defect rather
    than an inapplicable program.
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

    try:
        body = substitute(program.body, bindings(env))
    except UnboundParameterError as exc:
        # A program that fired and whose body cannot be substituted is a
        # mis-fire, not a crash: the episode must be recorded, not lose the run.
        return ReplayResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr="",
            unbound_parameter=True,
            reason=f"the body could not be run: {exc}",
        )
    # `git_env` inherits only the allowlisted variables (spec §9: the environment
    # is scrubbed) and redirects `HOME` into the sandbox, so `~` resolves onto
    # nothing a credential read could use. The guard still screens explicit
    # paths; this only makes one class of miss harmless.
    run_env = git_env(home=env.root)

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
