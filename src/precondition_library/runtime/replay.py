"""Executing a Program against an environment, with zero LLM calls.

INVARIANT — this module must not import `precondition_library.provider`,
directly or transitively. The project's central claim is that a replay costs no
tokens, so the cheapest way to make the claim false is an import that quietly
reintroduces a model call. tests/test_replay_isolated_from_provider.py walks
the import graph under `src/` and fails if provider becomes reachable from here.
That test is the guardrail; this docstring is just the explanation.

Replay also never trusts the program it runs: the body executes under a timeout
inside a throwaway sandbox, and its postconditions are re-checked afterwards
rather than taken on faith.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..program import GroundTruthResult


class ReplayResult(BaseModel):
    """What happened when a stored program ran."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    postconditions: GroundTruthResult | None = None
    """Populated whenever the body ran, even on failure — the evidence for demotion."""


def replay(program, env, *, timeout_s: float = 60.0) -> ReplayResult:
    """Run `program` in `env` under guard screening. Never calls a model."""
    raise NotImplementedError("implemented per plan: phase 3")


def check_postconditions(program, env) -> GroundTruthResult:
    """Run the program's own postconditions. No model."""
    raise NotImplementedError("implemented per plan: phase 3")
