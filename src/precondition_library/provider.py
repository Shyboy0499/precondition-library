"""The only place in this codebase allowed to talk to an LLM.

`runtime/replay.py` must never import this module — that invariant is enforced
by tests/test_replay_isolated_from_provider.py. If a replay episode ever
records a nonzero token count, the project's central claim is void, and we want
to learn that from a failing test rather than from a reviewer.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

DEFAULT_MODEL = "deepseek-chat"
"""The model the spec uses (design doc §5 provenance, §7 ledger `model`)."""

DEFAULT_BASE_URL = "https://api.deepseek.com"
"""DeepSeek's OpenAI-compatible base. The chat-completions path is appended."""


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
    text: str = ""
    """The assistant's prose. Legitimately empty when the model answers with a
    tool call rather than text, so it is not a field a caller may assume is set."""

    tool_calls: list[dict] = Field(default_factory=list)
    """The API's own `tool_calls` list, passed through unreshaped. Empty when the
    model answered with prose. A function call's `arguments` stays a JSON string,
    exactly as the API wrote it, so a caller that needs the command decodes it."""

    usage: TokenUsage
    model: str
    llm_calls: int = 1


class ProviderError(RuntimeError):
    """A completion could not be produced: a non-2xx response, or a body whose
    shape this client does not recognise.

    Deliberately not retried here. Spec §8 gives retry policy to the caller
    ("no silent retries, no invisible costs"): a client that backs off on its
    own hides the spend of the failed attempts, and the ledger cannot record
    what it cannot see. The caller is handed the facts it needs to decide:
    `status_code` is the HTTP status when the failure was a response, and None
    for a malformed body or a transport error, so a retry policy can be written
    without parsing the message text.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Provider(Protocol):
    """Minimal LLM boundary. Implementations must report real usage."""

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion: ...


class DeepSeekProvider:
    """DeepSeek's OpenAI-compatible endpoint.

    The default arm-1/compile provider. Kept deliberately thin so that a local
    model can be substituted without touching agent code.

    Configuration is passed in by the caller: this module reads no environment
    variables and no files, so a test can construct a provider without a key and
    the run configuration stays in one place.

    Cache field assumption
    ----------------------
    A prompt-cache hit is read from ``usage.prompt_cache_hit_tokens``. That is
    DeepSeek's own field, not OpenAI's ``prompt_tokens_details.cached_tokens``.
    The name is an **assumption that has not been verified against a live call**
    (none has been made; see tests/test_provider.py, which never reaches the
    network). If the field is absent or renamed, ``cached_tokens_in`` is 0: the
    call still succeeds and its real token cost is still recorded, but cache
    hits would go unaccounted. Verify with a live call by sending a repeated
    long prompt and checking that the response's usage block contains that key
    with a nonzero value.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._client = httpx.Client(
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    def complete(
        self, *, system: str, messages: list[dict], tools: list[dict] | None = None
    ) -> Completion:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools is not None:
            payload["tools"] = tools

        response = self._client.post("/chat/completions", json=payload)
        if not response.is_success:
            raise ProviderError(
                f"DeepSeek request failed with HTTP {response.status_code}: "
                f"{self._error_message(response)}",
                status_code=response.status_code,
            )
        return self._parse(response)

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """The API's own error text when it has one, else the raw body."""
        try:
            error = response.json()["error"]
            return str(error["message"])
        except (KeyError, TypeError, ValueError):
            return response.text

    def _parse(self, response: httpx.Response) -> Completion:
        """Read a completion out of the response body, or raise.

        Direct indexing on purpose: a body missing `usage` or `choices` must
        raise rather than fall back to zeros. A silently-zeroed usage would
        enter the ledger as "this episode was free", which corrupts the one
        measurement this project exists to report.

        `content` and `tool_calls` are the exception to that strictness. A model
        answering with a tool call sends `"content": null` and a populated
        `tool_calls`, so the contract is that a message carries one or the other,
        not that it carries text. `tool_calls` is passed through exactly as the
        API wrote it -- including the JSON-string `arguments` -- because the
        caller, not this client, knows how to read it.
        """
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            usage = body["usage"]
            tokens_in = usage["prompt_tokens"]
            tokens_out = usage["completion_tokens"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"malformed DeepSeek completion response: {exc!r}") from exc

        if not isinstance(message, dict):
            raise ProviderError(f"malformed DeepSeek completion response: message={message!r}")
        text = message.get("content")
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list) or (text is not None and not isinstance(text, str)):
            raise ProviderError(f"malformed DeepSeek completion response: {message!r}")
        if not text and not tool_calls:
            raise ProviderError(
                "malformed DeepSeek completion response: message has neither content nor tool_calls"
            )

        return Completion(
            text=text or "",
            tool_calls=tool_calls,
            usage=TokenUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached_tokens_in=usage.get("prompt_cache_hit_tokens", 0) or 0,
            ),
            model=body.get("model") or self._model,
        )
