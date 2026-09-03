"""Builds the configured AIClient (AI_PROVIDER=openai|anthropic) from Settings.

This is the one place that knows both concrete provider classes — everything
else (AnalysisService, the Streamlit UI) depends only on app.services.ai.base.AIClient.
"""

from __future__ import annotations

import logging

from app.config.settings import Settings
from app.exceptions import AIAuthError
from app.services.ai.base import AIClient


def get_ai_client(settings: Settings, logger: logging.Logger | None = None) -> AIClient:
    provider = settings.ai_provider.strip().lower()

    if provider == "openai":
        from app.services.ai.openai_client import OpenAIClient

        return OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            backoff_base_seconds=settings.ai_backoff_base_seconds,
            logger=logger,
        )

    if provider == "anthropic":
        from app.services.ai.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            backoff_base_seconds=settings.ai_backoff_base_seconds,
            logger=logger,
        )

    raise AIAuthError(f"Unknown AI_PROVIDER={provider!r} (expected 'openai' or 'anthropic')")
