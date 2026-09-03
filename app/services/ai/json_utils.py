"""Shared helper: call an AIClient and validate its response against a strict
Pydantic schema, retrying on invalid JSON / schema mismatches.

Used by analysis_service, safety_service, and generation_service so all three
share one retry policy for "the model didn't return well-formed JSON" — a
different failure mode from a network error, which AIClient.complete_json
already retries internally and lets propagate directly here.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.exceptions import AIInvalidResponseError
from app.services.ai.base import AIClient

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

T = TypeVar("T", bound=BaseModel)


def extract_json(raw_text: str) -> dict:
    """Strip optional ```json ... ``` fences, then json.loads."""
    cleaned = _CODE_FENCE_RE.sub("", raw_text.strip()).strip()
    return json.loads(cleaned)


def call_and_validate(
    client: AIClient,
    system_prompt: str,
    user_prompt: str,
    schema_cls: type[T],
    max_parse_retries: int = 2,
    logger: logging.Logger | None = None,
    log_context: str = "",
) -> T:
    """Call client.complete_json, parse the response as JSON, and validate it
    against `schema_cls`, retrying (re-asking the model, no backoff) up to
    `max_parse_retries` times on invalid JSON / schema mismatch.

    Network/auth errors from the client (AIError subclasses other than
    AIInvalidResponseError) propagate immediately — retrying those is
    AIClient.complete_json's job, not this function's.

    Raises AIInvalidResponseError if every attempt fails to validate.
    """
    log = logger or logging.getLogger("threads_tool")
    suffix = f" [{log_context}]" if log_context else ""
    last_error: Exception | None = None

    for attempt in range(1, max_parse_retries + 2):
        raw = client.complete_json(system_prompt, user_prompt)
        try:
            data = extract_json(raw)
            return schema_cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            log.warning(
                "AI応答の検証に失敗 (attempt %s/%s)%s: %s",
                attempt,
                max_parse_retries + 1,
                suffix,
                exc,
            )

    raise AIInvalidResponseError(
        f"AI応答が期待するJSONスキーマ({schema_cls.__name__}){suffix}に一致しませんでした: {last_error}"
    )
