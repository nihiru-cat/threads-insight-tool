"""Provider-agnostic AI client interface.

`AnalysisService` (app.services.analysis_service) only ever talks to this
interface, never to the OpenAI/Anthropic SDKs directly — swapping providers
is a config change (AI_PROVIDER), not a code change. See
app.services.ai.factory.get_ai_client.

Concrete subclasses implement `_call_provider`, which should raise one of
the AI* exceptions from app.exceptions (mapped from the provider SDK's own
exception types) rather than letting SDK-specific exceptions escape. The
retry loop here is generic: it retries AIRateLimitError/AIServerError/
AITimeoutError with exponential backoff up to `max_retries`, and lets
AIAuthError / AIInvalidResponseError propagate immediately (they won't
succeed on retry).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from app.exceptions import AIRateLimitError, AIServerError, AITimeoutError


class AIClient(ABC):
    def __init__(
        self,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._logger = logger or logging.getLogger("threads_tool")

    @abstractmethod
    def _call_provider(self, system_prompt: str, user_prompt: str) -> str:
        """Call the underlying AI API once and return the raw text response.

        Must raise an app.exceptions.AI* subclass on failure (never let a
        provider SDK exception escape this method).
        """

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        """Call the provider, retrying transient errors with backoff.

        Returns the raw text response (expected to be JSON, possibly wrapped
        in markdown code fences — parsing/validation happens in
        app.services.analysis_service).
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._call_provider(system_prompt, user_prompt)
            except (AIRateLimitError, AIServerError, AITimeoutError) as exc:
                if attempt > self._max_retries:
                    raise
                delay = self._backoff_base_seconds * (2 ** (attempt - 1))
                self._logger.warning(
                    "AI provider transient error (attempt %s/%s), retrying in %.1fs: %s",
                    attempt,
                    self._max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)

    def close(self) -> None:  # pragma: no cover - overridden where needed
        pass

    def __enter__(self) -> "AIClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
