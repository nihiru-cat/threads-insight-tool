"""Tests for OpenAIEmbeddingSimilarityChecker's cosine similarity math and
exception mapping, using real `openai` SDK exception classes (see
tests/test_ai_openai_client.py for why plain httpx objects work here)."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.exceptions import AIAuthError, AIRateLimitError
from app.services.similarity.openai_embedding_similarity import OpenAIEmbeddingSimilarityChecker, _cosine_similarity


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/embeddings")


def _status_error(cls, status_code: int, message: str = "error"):
    resp = httpx.Response(status_code, request=_request(), json={"error": message})
    return cls(message, response=resp, body=None)


def make_checker(monkeypatch, create_fn) -> OpenAIEmbeddingSimilarityChecker:
    checker = OpenAIEmbeddingSimilarityChecker(api_key="fake-key")
    monkeypatch.setattr(checker._client.embeddings, "create", create_fn)
    return checker


def test_cosine_similarity_identical_vectors_is_1():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_0():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_0():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_similarity_returns_cosine_of_two_embeddings(monkeypatch):
    fake_response = SimpleNamespace(
        data=[
            SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            SimpleNamespace(index=1, embedding=[1.0, 0.0]),
        ]
    )
    checker = make_checker(monkeypatch, lambda **kwargs: fake_response)
    assert checker.similarity("a", "b") == pytest.approx(1.0)


def test_similarity_empty_text_returns_0_without_calling_api(monkeypatch):
    calls = {"n": 0}

    def fail_if_called(**kwargs):
        calls["n"] += 1
        raise AssertionError("should not be called")

    checker = make_checker(monkeypatch, fail_if_called)
    assert checker.similarity("", "something") == 0.0
    assert calls["n"] == 0


def test_maps_authentication_error(monkeypatch):
    def raise_auth(**kwargs):
        raise _status_error(openai.AuthenticationError, 401)

    checker = make_checker(monkeypatch, raise_auth)
    with pytest.raises(AIAuthError):
        checker.similarity("a", "b")


def test_maps_rate_limit_error(monkeypatch):
    def raise_rl(**kwargs):
        raise _status_error(openai.RateLimitError, 429)

    checker = make_checker(monkeypatch, raise_rl)
    with pytest.raises(AIRateLimitError):
        checker.similarity("a", "b")


def test_missing_api_key_raises_immediately():
    with pytest.raises(AIAuthError):
        OpenAIEmbeddingSimilarityChecker(api_key="")
