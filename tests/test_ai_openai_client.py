"""Tests for OpenAIClient's exception mapping and response parsing.

Exercises real `openai` SDK exception classes (constructed with plain httpx
Request/Response objects, which the SDK accepts structurally) rather than
hand-rolled fakes, so a mismatch with the actual SDK's exception shape would
show up here.
"""

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.exceptions import (
    AIAuthError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServerError,
    AITimeoutError,
)
from app.services.ai.openai_client import OpenAIClient


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _status_error(cls, status_code: int, message: str = "error"):
    resp = httpx.Response(status_code, request=_request(), json={"error": message})
    return cls(message, response=resp, body=None)


def make_client(monkeypatch, create_fn) -> OpenAIClient:
    client = OpenAIClient(api_key="fake-key", model="gpt-4o-mini", max_retries=1, backoff_base_seconds=0)
    monkeypatch.setattr(client._client.chat.completions, "create", create_fn)
    return client


def test_returns_message_content_on_success(monkeypatch):
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))]
    )
    client = make_client(monkeypatch, lambda **kwargs: fake_response)

    assert client.complete_json("sys", "user") == '{"a": 1}'


def test_maps_authentication_error(monkeypatch):
    def raise_auth(**kwargs):
        raise _status_error(openai.AuthenticationError, 401)

    client = make_client(monkeypatch, raise_auth)
    with pytest.raises(AIAuthError):
        client.complete_json("sys", "user")


def test_maps_rate_limit_error_and_retries(monkeypatch):
    calls = {"n": 0}

    def raise_rate_limit(**kwargs):
        calls["n"] += 1
        raise _status_error(openai.RateLimitError, 429)

    client = make_client(monkeypatch, raise_rate_limit)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda _s: None)

    with pytest.raises(AIRateLimitError):
        client.complete_json("sys", "user")
    assert calls["n"] == 2  # initial attempt + 1 retry (max_retries=1)


def test_maps_server_error(monkeypatch):
    def raise_server(**kwargs):
        raise _status_error(openai.InternalServerError, 500)

    client = make_client(monkeypatch, raise_server)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda _s: None)
    with pytest.raises(AIServerError):
        client.complete_json("sys", "user")


def test_maps_timeout_error(monkeypatch):
    def raise_timeout(**kwargs):
        raise openai.APITimeoutError(request=_request())

    client = make_client(monkeypatch, raise_timeout)
    monkeypatch.setattr("app.services.ai.base.time.sleep", lambda _s: None)
    with pytest.raises(AITimeoutError):
        client.complete_json("sys", "user")


def test_maps_bad_request_to_invalid_response_without_retry(monkeypatch):
    calls = {"n": 0}

    def raise_bad_request(**kwargs):
        calls["n"] += 1
        raise _status_error(openai.BadRequestError, 400)

    client = make_client(monkeypatch, raise_bad_request)
    with pytest.raises(AIInvalidResponseError):
        client.complete_json("sys", "user")
    assert calls["n"] == 1  # not retried


def test_missing_api_key_raises_immediately():
    with pytest.raises(AIAuthError):
        OpenAIClient(api_key="", model="gpt-4o-mini")
