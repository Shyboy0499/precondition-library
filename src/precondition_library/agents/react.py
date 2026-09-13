"""Arm 1: the ReAct baseline. No library, full LLM cost per episode.

This arm is the honest yardstick the other two are measured against, so it must
be given every advantage a reasonable engineer would give it by hand: a good
system prompt, the same tool surface the compiled programs get, and the same
sandbox. A deliberately crippled baseline would make the other arms look better
and the result worthless.
"""

from __future__ import annotations

from ..program import EpisodeOutcome
from ..provider import Provider


def solve(
    signature, env, provider: Provider, *, max_steps: int = 12
) -> tuple[EpisodeOutcome, list[dict]]:
    """Observe -> act -> observe until the environment checks out or we give up.

    Returns the outcome and the full message transcript. The transcript is what
    the compile step later reads, so it is a first-class output here rather than
    a debugging aid.
    """
    raise NotImplementedError("implemented per plan: phase 1")


def available_tools() -> list[dict]:
    """Tool schemas shared across all three arms, so the comparison is fair."""
    raise NotImplementedError("implemented per plan: phase 1")
