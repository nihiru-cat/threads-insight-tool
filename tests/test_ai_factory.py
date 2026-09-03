import pytest

from app.config.settings import Settings
from app.exceptions import AIAuthError
from app.services.ai.anthropic_client import AnthropicClient
from app.services.ai.factory import get_ai_client
from app.services.ai.openai_client import OpenAIClient


def test_factory_builds_anthropic_client():
    settings = Settings(ai_provider="anthropic", anthropic_api_key="fake-key")
    client = get_ai_client(settings)
    assert isinstance(client, AnthropicClient)


def test_factory_builds_openai_client():
    settings = Settings(ai_provider="openai", openai_api_key="fake-key")
    client = get_ai_client(settings)
    assert isinstance(client, OpenAIClient)


def test_factory_rejects_unknown_provider():
    settings = Settings(ai_provider="not-a-real-provider")
    with pytest.raises(AIAuthError):
        get_ai_client(settings)


def test_factory_propagates_missing_api_key():
    settings = Settings(ai_provider="anthropic", anthropic_api_key="")
    with pytest.raises(AIAuthError):
        get_ai_client(settings)
