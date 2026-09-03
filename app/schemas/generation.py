"""Pydantic schema for an AI-generated original post draft.

Strict (`extra="forbid"`) like app.schemas.analysis — the model must return
exactly one key. The prompt that produces this (see
app.services.generation_service.SYSTEM_PROMPT) is built from ONLY the
abstracted PostAnalysis fields (theme/hook/structure/cta/target_reader) of
the source post — never the source post's raw text — so literal copying is
structurally prevented rather than merely discouraged. The similarity check
(app.services.generation_service) is the second, independent line of
defense against copying/paraphrasing that slips through anyway.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GeneratedPostDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_text: str = Field(description="生成されたThreads投稿案の本文")

    @field_validator("generated_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
