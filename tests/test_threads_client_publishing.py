"""Tests for the Phase 5 publishing methods on ThreadsClient (container
create -> wait -> publish -> fetch permalink)."""

import httpx
import pytest

from app.exceptions import ThreadsAuthError, ThreadsInvalidResponseError, ThreadsRateLimitError
from app.services.threads_client import ThreadsClient


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr("app.services.threads_client.time.sleep", lambda _seconds: None)


def make_client(handler, **kwargs) -> ThreadsClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return ThreadsClient(access_token="fake-token", http_client=http_client, max_retries=2, **kwargs)


def test_create_container_returns_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).startswith("https://graph.threads.net/v1.0/12345/threads")
        assert request.url.params["media_type"] == "TEXT"
        assert request.url.params["text"] == "hello world"
        return httpx.Response(200, json={"id": "container-1"})

    client = make_client(handler)
    container_id = client.create_container("12345", "hello world")
    assert container_id == "container-1"


def test_create_container_raises_on_missing_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = make_client(handler)
    with pytest.raises(ThreadsInvalidResponseError):
        client.create_container("12345", "hello")


def test_create_container_maps_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid token"})

    client = make_client(handler)
    with pytest.raises(ThreadsAuthError):
        client.create_container("12345", "hello")


def test_publish_container_returns_media_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://graph.threads.net/v1.0/12345/threads_publish")
        assert request.url.params["creation_id"] == "container-1"
        return httpx.Response(200, json={"id": "media-1"})

    client = make_client(handler)
    media_id = client.publish_container("12345", "container-1")
    assert media_id == "media-1"


def test_publish_container_retries_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"id": "media-1"})

    client = make_client(handler)
    media_id = client.publish_container("12345", "container-1")
    assert media_id == "media-1"
    assert calls["n"] == 2


def test_publish_container_raises_rate_limit_when_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = make_client(handler)
    with pytest.raises(ThreadsRateLimitError):
        client.publish_container("12345", "container-1")


def test_get_permalink_returns_value():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://graph.threads.net/v1.0/media-1")
        assert request.url.params["fields"] == "permalink"
        return httpx.Response(200, json={"id": "media-1", "permalink": "https://www.threads.net/@u/post/media-1"})

    client = make_client(handler)
    permalink = client.get_permalink("media-1")
    assert permalink == "https://www.threads.net/@u/post/media-1"


def test_publish_post_runs_full_flow_and_waits(monkeypatch):
    calls = []
    sleep_calls = []
    monkeypatch.setattr("app.services.threads_client.time.sleep", lambda s: sleep_calls.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "media-1"})
        return httpx.Response(200, json={"id": "media-1", "permalink": "https://www.threads.net/@u/post/media-1"})

    client = make_client(handler)
    result = client.publish_post("12345", "hello world", wait_seconds=30)

    assert result.threads_post_id == "media-1"
    assert result.permalink == "https://www.threads.net/@u/post/media-1"
    assert len(calls) == 3
    assert sleep_calls == [30]


def test_publish_post_succeeds_even_if_permalink_fetch_fails(monkeypatch):
    """A post is live on Threads as soon as publish_container succeeds. If
    fetching its permalink afterward fails, publish_post must NOT raise —
    doing so would make a caller think the post never went out and retry,
    causing a real duplicate post."""
    monkeypatch.setattr("app.services.threads_client.time.sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "media-1"})
        return httpx.Response(500, text="server error")

    client = make_client(handler)
    result = client.publish_post("12345", "hello world", wait_seconds=0)

    assert result.threads_post_id == "media-1"
    assert result.permalink is None


def test_publish_post_skips_wait_when_zero(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("app.services.threads_client.time.sleep", lambda s: sleep_calls.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "media-1"})
        return httpx.Response(200, json={"id": "media-1", "permalink": None})

    client = make_client(handler)
    client.publish_post("12345", "hello world", wait_seconds=0)

    assert sleep_calls == []
