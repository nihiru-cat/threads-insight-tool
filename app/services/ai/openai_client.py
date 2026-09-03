"""OpenAI implementation of AIClient.

Verified against the installed `openai` SDK (see requirements.txt) by
introspecting the actual package rather than assuming API shape:
    OpenAI(api_key=..., timeout=..., max_retries=...)
    client.chat.completions.create(model=..., messages=[...], response_format={"type": "json_object"})
        -> response.choices[0].message.content : str
Exception hierarchy (openai.<Name>.__mro__):
    RateLimitError, AuthenticationError, InternalServerError, BadRequestError -> APIStatusError -> APIError
    APITimeoutError -> APIConnectionError -> APIError
"""

from __future__ import annotations

import logging

import openai

from app.exceptions import (
    AIAuthError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServerError,
    AITimeoutError,
)
from app.services.ai.base import AIClient


class OpenAIClient(AIClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(max_retries=max_retries, backoff_base_seconds=backoff_base_seconds, logger=logger)
        if not api_key:
            raise AIAuthError("OPENAI_API_KEY is not set")
        self._model = model
        # max_retries=0 on the SDK client: AIClient.complete_json owns the retry loop.
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def _call_provider(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
        except openai.AuthenticationError as exc:
            raise AIAuthError(f"OpenAI auth error: {exc}") from exc
        except openai.RateLimitError as exc:
            raise AIRateLimitError(f"OpenAI rate limited: {exc}") from exc
        except openai.APITimeoutError as exc:
            raise AITimeoutError(f"OpenAI request timed out: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise AIServerError(f"OpenAI connection error: {exc}") from exc
        except openai.APIStatusError as exc:
            if 500 <= exc.status_code < 600:
                raise AIServerError(f"OpenAI server error ({exc.status_code}): {exc}") from exc
            raise AIInvalidResponseError(f"OpenAI request error ({exc.status_code}): {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise AIInvalidResponseError("OpenAI response had empty content")
        return content

    def close(self) -> None:
        self._client.close()
