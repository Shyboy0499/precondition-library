"""The only place in this codebase allowed to talk to an LLM.

`runtime/replay.py` must never import this module — that invariant is enforced
by tests/test_replay_isolated_from_provider.py. If a replay episode ever
records a nonzero token count, the project's central claim is void, and we want
to learn that from a failing test rather than from a reviewer.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class TokenUsage(BaseModel):
    """Token accounting, read from the API response rather than estimated."""

    tokens_in: int
    tokens_out: int
    cached_tokens_in: int = 0
    """Provider-side prompt-cache hits. Reported separately because a cache hit
    makes the ReAct baseline look cheaper than the work actually performed."""

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


class Completion(BaseModel):
    text: str
    usage: TokenUsage
    model: str
    llm_calls: int = 1


class Provider(Protocol):
    """Minimal LLM boundary. Implementations must report real usage."""

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion: ...


class DeepSeekProvider:
    """DeepSeek's OpenAI-compatible endpoint.

    The default arm-1/compile provider. Kept deliberately thin so that a local
    model can be substituted without touching agent code.
    """

    def __init__(
        self, api_key: str, model: str = "deepseek-chat", base_url: str | None = None
    ) -> None:
        raise NotImplementedError("implemented per plan: phase 1")

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion:
        raise NotImplementedError("implemented per plan: phase 1")
