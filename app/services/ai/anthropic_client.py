"""Anthropic implementation of AIClient.

Verified against the installed `anthropic` SDK (see requirements.txt) by
introspecting the actual package rather than assuming API shape:
    Anthropic(api_key=..., timeout=..., max_retries=...)
    client.messages.create(model=..., max_tokens=..., system=..., messages=[{"role": "user", "content": ...}])
        -> response.content : list of blocks; text blocks have .type == "text" and .text : str
Exception hierarchy (anthropic.<Name>.__mro__):
    RateLimitError, AuthenticationError, InternalServerError, OverloadedError -> APIStatusError -> APIError
    APITimeoutError -> APIConnectionError -> APIError
"""

from __future__ import annotations

import logging

import anthropic

from app.exceptions import (
    AIAuthError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServerError,
    AITimeoutError,
)
from app.services.ai.base import AIClient


class AnthropicClient(AIClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        max_tokens: int = 2048,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(max_retries=max_retries, backoff_base_seconds=backoff_base_seconds, logger=logger)
        if not api_key:
            raise AIAuthError("ANTHROPIC_API_KEY is not set")
        self._model = model
        self._max_tokens = max_tokens
        # max_retries=0 on the SDK client: AIClient.complete_json owns the retry loop.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def _call_provider(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError as exc:
            raise AIAuthError(f"Anthropic auth error: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise AIRateLimitError(f"Anthropic rate limited: {exc}") from exc
        except anthropic.APITimeoutError as exc:
            raise AITimeoutError(f"Anthropic request timed out: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIServerError(f"Anthropic connection error: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise AIServerError(f"Anthropic server error ({exc.status_code}): {exc}") from exc
            raise AIInvalidResponseError(f"Anthropic request error ({exc.status_code}): {exc}") from exc

        text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        content = "".join(text_blocks).strip()
        if not content:
            raise AIInvalidResponseError("Anthropic response had no text content")
        return content

    def close(self) -> None:
        self._client.close()
