"""The provider boundary, asserted without a network.

Every provider in this module is constructed with an `httpx.MockTransport`, so
no test here opens a socket or needs an API key. That is not a convenience: the
ledger's numbers are only meaningful if they come from real responses, and a
test suite that quietly reached a live endpoint would make the cost of running
CI depend on an external service. The cache field in particular cannot be
verified without a live call, so it is exercised against a synthetic body that
encodes the assumed name, and the assumption is stated in `provider.py`.
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import FakeProvider

from precondition_library.provider import (
    Completion,
    DeepSeekProvider,
    Provider,
    ProviderError,
    TokenUsage,
)

URL = "https://api.deepseek.com/chat/completions"


def _ok_body(
    *,
    content: str | None = "done",
    tool_calls: list | None = None,
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    cached: int | None = 3,
    model: str = "deepseek-chat",
) -> dict:
    usage: dict = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
    if cached is not None:
        usage["prompt_cache_hit_tokens"] = cached
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"model": model, "choices": [{"message": message}], "usage": usage}


def _provider(transport: httpx.BaseTransport, *, model: str = "deepseek-chat") -> DeepSeekProvider:
    """The only way this module builds a provider, so no test can use a live one."""
    return DeepSeekProvider(api_key="test-key", model=model, transport=transport)


def _capturing(body: dict | None = None, status: int = 200) -> tuple[httpx.MockTransport, list]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=body if body is not None else _ok_body())

    return httpx.MockTransport(handler), calls


def test_no_test_here_reaches_the_network() -> None:
    """Sentinel for the module docstring: only `_provider` builds a client, and it
    always injects a transport. If a real call were attempted the address below
    would be hit; proving it was not is structural, so this pins the helper."""
    transport, calls = _capturing()
    _provider(transport).complete(system="s", messages=[])
    assert len(calls) == 1


def test_request_wire_shape_without_tools() -> None:
    transport, calls = _capturing()
    _provider(transport).complete(
        system="be careful",
        messages=[{"role": "user", "content": "hi"}],
    )

    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == URL
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["content-type"] == "application/json"

    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"] == [
        {"role": "system", "content": "be careful"},
        {"role": "user", "content": "hi"},
    ]
    assert "tools" not in payload


def test_request_wire_shape_with_tools() -> None:
    tools = [{"type": "function", "function": {"name": "run"}}]
    transport, calls = _capturing()
    _provider(transport).complete(system="s", messages=[], tools=tools)
    assert json.loads(calls[0].content)["tools"] == tools


def test_response_parses_into_real_usage() -> None:
    transport, _ = _capturing(_ok_body(prompt_tokens=120, completion_tokens=34, cached=100))
    completion = _provider(transport).complete(system="s", messages=[])

    assert isinstance(completion, Completion)
    assert completion.text == "done"
    assert completion.usage == TokenUsage(tokens_in=120, tokens_out=34, cached_tokens_in=100)
    assert completion.usage.total == 154
    assert completion.llm_calls == 1
    assert completion.model == "deepseek-chat"
    assert completion.tool_calls == []


def test_tool_calls_without_content_parse_and_surface_unreshaped() -> None:
    """The API sends `content: null` when the model calls a tool. That is a valid
    completion, not malformed, and the caller needs the calls in the API's own
    shape -- `arguments` stays the JSON string the API wrote."""
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "run_git", "arguments": '{"command": "git status --porcelain"}'},
        }
    ]
    transport, _ = _capturing(_ok_body(content=None, tool_calls=calls))
    completion = _provider(transport).complete(system="s", messages=[])

    assert completion.text == ""
    assert completion.tool_calls == calls
    assert completion.usage == TokenUsage(tokens_in=11, tokens_out=7, cached_tokens_in=3)


def test_absent_cache_field_defaults_to_zero() -> None:
    """The assumed cache key cannot be checked live; this fixes the fallback rule."""
    transport, _ = _capturing(_ok_body(cached=None))
    completion = _provider(transport).complete(system="s", messages=[])
    assert completion.usage.cached_tokens_in == 0
    assert completion.usage.tokens_in == 11


def test_response_model_is_reported_when_the_body_names_it() -> None:
    """Model drift is a ledger confound, so the body's identifier wins over config."""
    transport, _ = _capturing(_ok_body(model="deepseek-chat-0913"))
    completion = _provider(transport, model="deepseek-chat").complete(system="s", messages=[])
    assert completion.model == "deepseek-chat-0913"


def test_non_2xx_raises_with_status_and_api_message() -> None:
    transport, _ = _capturing(
        {"error": {"message": "Rate limit exceeded", "type": "rate_limit"}}, status=429
    )
    with pytest.raises(ProviderError) as excinfo:
        _provider(transport).complete(system="s", messages=[])

    message = str(excinfo.value)
    assert "429" in message
    assert "Rate limit exceeded" in message


def test_non_2xx_without_json_still_reports_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    with pytest.raises(ProviderError, match="500"):
        _provider(httpx.MockTransport(handler)).complete(system="s", messages=[])


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"choices": [{"message": {"content": "x"}}]}, id="missing-usage"),
        pytest.param({"usage": {"prompt_tokens": 1, "completion_tokens": 2}}, id="missing-choices"),
        pytest.param({"usage": {}, "choices": []}, id="empty-choices"),
        pytest.param(
            {
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                "choices": [{"message": {"role": "assistant", "content": None}}],
            },
            id="no-content-and-no-tool-calls",
        ),
    ],
)
def test_malformed_body_raises_rather_than_zeroing_usage(body: dict) -> None:
    """A zeroed usage would enter the ledger as a free episode. It must not."""
    transport, _ = _capturing(body)
    with pytest.raises(ProviderError):
        _provider(transport).complete(system="s", messages=[])


def test_fake_provider_is_usable_wherever_a_provider_is_expected() -> None:
    """A Protocol cannot be isinstance-checked at runtime, so pass the fake to a
    function that only accepts `Provider`: static compatibility is the assertion."""

    def consume(provider: Provider) -> Completion:
        return provider.complete(system="sys", messages=[{"role": "user", "content": "go"}])

    expected = Completion(text="ok", usage=TokenUsage(tokens_in=5, tokens_out=2), model="fake")
    fake = FakeProvider(expected)

    assert consume(fake) is expected


def test_fake_provider_records_calls_and_can_raise() -> None:
    fake = FakeProvider(raises=ProviderError("boom"))
    with pytest.raises(ProviderError, match="boom"):
        fake.complete(system="sys", messages=[{"role": "user", "content": "go"}], tools=[])

    assert fake.calls == [
        {
            "system": "sys",
            "messages": [{"role": "user", "content": "go"}],
            "tools": [],
        }
    ]


def test_fake_provider_refuses_to_invent_a_completion() -> None:
    with pytest.raises(AssertionError, match="empty queue"):
        FakeProvider().complete(system="s", messages=[])
