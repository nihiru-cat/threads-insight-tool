import httpx
import pytest

from app.exceptions import (
    ThreadsAuthError,
    ThreadsInvalidResponseError,
    ThreadsRateLimitError,
    ThreadsServerError,
    ThreadsTimeoutError,
)
from app.services.threads_client import ThreadsClient


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr("app.services.threads_client.time.sleep", lambda _seconds: None)


def make_client(handler, **kwargs) -> ThreadsClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return ThreadsClient(access_token="fake-token", http_client=http_client, max_retries=2, **kwargs)


def test_missing_access_token_raises_immediately():
    with pytest.raises(ThreadsAuthError):
        ThreadsClient(access_token="")


def test_search_returns_parsed_posts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "占い"
        assert request.url.params["search_type"] == "TOP"
        assert "fake-token" in request.url.params["access_token"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "123",
                        "text": "hello",
                        "timestamp": "2024-05-09T20:14:38+0000",
                        "permalink": "https://www.threads.net/@u/post/123",
                        "username": "u",
                        "media_type": "TEXT",
                    }
                ]
            },
        )

    client = make_client(handler)
    posts = client.search(keyword="占い", search_type="TOP")

    assert len(posts) == 1
    assert posts[0].id == "123"
    assert posts[0].username == "u"


def test_search_retries_on_429_then_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    posts = client.search(keyword="占い")

    assert posts == []
    assert calls["count"] == 2


def test_search_raises_after_exhausting_retries_on_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = make_client(handler)
    with pytest.raises(ThreadsServerError):
        client.search(keyword="占い")


def test_search_raises_rate_limit_error_when_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = make_client(handler)
    with pytest.raises(ThreadsRateLimitError):
        client.search(keyword="占い")


def test_search_raises_auth_error_without_retry():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"error": "invalid token"})

    client = make_client(handler)
    with pytest.raises(ThreadsAuthError):
        client.search(keyword="占い")
    assert calls["count"] == 1


def test_search_raises_invalid_response_on_bad_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

    client = make_client(handler)
    with pytest.raises(ThreadsInvalidResponseError):
        client.search(keyword="占い")


def test_search_raises_timeout_after_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(ThreadsTimeoutError):
        client.search(keyword="占い")
