"""Tests for AnthropicClient's exception mapping and response parsing.

Exercises real `anthropic` SDK exception classes (constructed with plain
httpx Request/Response objects, which the SDK accepts structurally).
"""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.exceptions import AIAuthError, AIRateLimitError, AITimeoutError
from app.services.ai.anthropic_client import AnthropicClient


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status_code: int, message: str = "error"):
    resp = httpx.Response(status_code, request=_request(), json={"error": message})
    return cls(message, response=resp, body=None)


def make_client(monkeypatch, create_fn) -> AnthropicClient:
    client = AnthropicClient(api_key="fake-key", model="claude-sonnet-5", max_retries=1, backoff_base_seconds=0)
    monkeypatch.setattr(client._client.messages, "create", create_fn)
    return client


def test_returns_joined_text_blocks_on_success(monkeypatch):
    fake_response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text='{"a": '),
            SimpleNamespace(type="text", text="1}"),
        ]
    )
    client = make_client(monkeypatch, lambda **kwargs: fake_response)

    assert client.complete_json("sys", "user") == '{"a": 1}'


def test_maps_authentication_error(monkeypatch):
    def raise_auth(**kwargs):
        raise _status_error(anthropic.AuthenticationError, 401)

    client = make_client(monkeypatch, raise_auth)
    with pytest.raises(AIAuthError):
        client.complete_json("sys", "user")


def test_maps_rate_limit_error_and_retries(monkeypatch):
    calls = {"n": 0}

    def raise_rate_limit(**kwargs):
        calls["n"] += 1
        raise _status_error(anthropic.RateLimitError, 429)

    client = make_client(monkeypatch, raise_rate_limit)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda _s: None)

    with pytest.raises(AIRateLimitError):
        client.complete_json("sys", "user")
    assert calls["n"] == 2


def test_maps_timeout_error(monkeypatch):
    def raise_timeout(**kwargs):
        raise anthropic.APITimeoutError(request=_request())

    client = make_client(monkeypatch, raise_timeout)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda _s: None)
    with pytest.raises(AITimeoutError):
        client.complete_json("sys", "user")


def test_missing_api_key_raises_immediately():
    with pytest.raises(AIAuthError):
        AnthropicClient(api_key="", model="claude-sonnet-5")
