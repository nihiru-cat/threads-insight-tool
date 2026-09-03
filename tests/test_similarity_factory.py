import pytest

from app.config.settings import Settings
from app.exceptions import AIAuthError, SimilarityBackendError
from app.services.similarity.factory import get_similarity_checker
from app.services.similarity.openai_embedding_similarity import OpenAIEmbeddingSimilarityChecker
from app.services.similarity.string_similarity import StringSimilarityChecker


def test_string_backend_forced():
    settings = Settings(similarity_backend="string", openai_api_key="fake-key")
    checker = get_similarity_checker(settings)
    assert isinstance(checker, StringSimilarityChecker)


def test_openai_embedding_backend_forced():
    settings = Settings(similarity_backend="openai_embedding", openai_api_key="fake-key")
    checker = get_similarity_checker(settings)
    assert isinstance(checker, OpenAIEmbeddingSimilarityChecker)


def test_openai_embedding_backend_forced_without_key_raises():
    settings = Settings(similarity_backend="openai_embedding", openai_api_key="")
    with pytest.raises(AIAuthError):
        get_similarity_checker(settings)


def test_auto_uses_openai_embedding_when_key_present():
    settings = Settings(similarity_backend="auto", openai_api_key="fake-key")
    checker = get_similarity_checker(settings)
    assert isinstance(checker, OpenAIEmbeddingSimilarityChecker)


def test_auto_falls_back_to_string_without_key():
    settings = Settings(similarity_backend="auto", openai_api_key="")
    checker = get_similarity_checker(settings)
    assert isinstance(checker, StringSimilarityChecker)


def test_unknown_backend_raises():
    settings = Settings(similarity_backend="not-a-real-backend")
    with pytest.raises(SimilarityBackendError):
        get_similarity_checker(settings)
