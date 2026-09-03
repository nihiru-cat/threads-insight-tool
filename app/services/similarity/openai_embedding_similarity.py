"""OpenAI-embedding-based semantic similarity.

Verified against the installed `openai` SDK by introspecting the actual
package (same approach as app.services.ai.openai_client):
    client.embeddings.create(model=..., input=[text_a, text_b])
        -> response.data[i].embedding : list[float]
Anthropic has no embeddings endpoint, so this backend is OpenAI-only — see
app.services.similarity.factory for how the backend is chosen.
"""

from __future__ import annotations

import logging
import math

import openai

from app.exceptions import (
    AIAuthError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServerError,
    AITimeoutError,
)
from app.services.similarity.base import SimilarityChecker


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    # Clamp for float rounding (cosine similarity is mathematically in [-1, 1]).
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


class OpenAIEmbeddingSimilarityChecker(SimilarityChecker):
    backend_name = "openai_embedding"

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        timeout_seconds: float = 30.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if not api_key:
            raise AIAuthError("OPENAI_API_KEY is not set (required for the openai_embedding similarity backend)")
        self._model = model
        self._logger = logger or logging.getLogger("threads_tool")
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    def similarity(self, text_a: str, text_b: str) -> float:
        if not text_a or not text_b:
            return 0.0
        try:
            response = self._client.embeddings.create(model=self._model, input=[text_a, text_b])
        except openai.AuthenticationError as exc:
            raise AIAuthError(f"OpenAI auth error (embeddings): {exc}") from exc
        except openai.RateLimitError as exc:
            raise AIRateLimitError(f"OpenAI rate limited (embeddings): {exc}") from exc
        except openai.APITimeoutError as exc:
            raise AITimeoutError(f"OpenAI request timed out (embeddings): {exc}") from exc
        except openai.APIConnectionError as exc:
            raise AIServerError(f"OpenAI connection error (embeddings): {exc}") from exc
        except openai.APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise AIServerError(f"OpenAI server error ({exc.status_code}, embeddings): {exc}") from exc
            raise AIInvalidResponseError(f"OpenAI request error ({exc.status_code}, embeddings): {exc}") from exc

        vectors = sorted(response.data, key=lambda d: d.index)
        if len(vectors) != 2:
            raise AIInvalidResponseError(f"Expected 2 embeddings, got {len(vectors)}")
        return _cosine_similarity(vectors[0].embedding, vectors[1].embedding)

    def close(self) -> None:
        self._client.close()
