"""Builds the configured SimilarityChecker from Settings.

SIMILARITY_BACKEND=auto (default): use OpenAI embeddings if OPENAI_API_KEY is
set (Anthropic has no embeddings endpoint), otherwise fall back to the
string-based backend and log that semantic similarity is degraded.
SIMILARITY_BACKEND=string: always use the string-based backend.
SIMILARITY_BACKEND=openai_embedding: always use OpenAI embeddings (raises
AIAuthError if OPENAI_API_KEY isn't set).
"""

from __future__ import annotations

import logging

from app.config.settings import Settings
from app.exceptions import SimilarityBackendError
from app.services.similarity.base import SimilarityChecker
from app.services.similarity.string_similarity import StringSimilarityChecker


def get_similarity_checker(settings: Settings, logger: logging.Logger | None = None) -> SimilarityChecker:
    log = logger or logging.getLogger("threads_tool")
    backend = settings.similarity_backend.strip().lower()

    if backend == "string":
        return StringSimilarityChecker()

    if backend == "openai_embedding":
        from app.services.similarity.openai_embedding_similarity import OpenAIEmbeddingSimilarityChecker

        return OpenAIEmbeddingSimilarityChecker(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            timeout_seconds=settings.ai_timeout_seconds,
            logger=log,
        )

    if backend == "auto":
        if settings.openai_api_key:
            from app.services.similarity.openai_embedding_similarity import OpenAIEmbeddingSimilarityChecker

            return OpenAIEmbeddingSimilarityChecker(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
                timeout_seconds=settings.ai_timeout_seconds,
                logger=log,
            )
        log.warning(
            "OPENAI_API_KEYが未設定のため、意味的類似度チェックは文字列類似度(string)にフォールバックします。"
            "精度を上げるにはOPENAI_API_KEYを設定してください（Anthropicはembeddings APIを提供していません）。"
        )
        return StringSimilarityChecker()

    raise SimilarityBackendError(
        f"Unknown SIMILARITY_BACKEND={backend!r} (expected 'auto', 'string', or 'openai_embedding')"
    )
