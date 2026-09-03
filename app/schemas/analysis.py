"""Pydantic schema for AI-generated post analysis.

Strict by design (`extra="forbid"`, non-empty strings, 0-100 score): the AI
provider's raw text response is parsed as JSON and validated against this
model before it's ever saved. A response that doesn't match exactly is
treated as a parse failure and retried (see app.services.analysis_service),
never silently coerced or partially accepted.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

ANALYSIS_FIELDS = [
    "theme",
    "hook",
    "structure",
    "emotion",
    "cta",
    "target_reader",
    "viral_score",
    "reason",
]


class PostAnalysisResult(BaseModel):
    """The strict schema an AI response must match for one post."""

    model_config = ConfigDict(extra="forbid")

    theme: str = Field(description="投稿の主題カテゴリ（例: 恋愛運, 金運, 自己啓発 など）")
    hook: str = Field(description="冒頭フックの型・要約（例: 断定型の警告, 共感型の問いかけ など）")
    structure: str = Field(description="文章構成の型（例: 結論先出し→理由→具体例→CTA など）")
    emotion: str = Field(description="訴求している主な感情（例: 不安, 希望, 好奇心 など）")
    cta: str = Field(description="読者に促している行動の型（例: 保存を促す, コメントを促す など）")
    target_reader: str = Field(description="想定読者層（例: 復縁を望む20-30代女性 など）")
    viral_score: int = Field(ge=0, le=100, description="伸びやすさの推定スコア(0-100)")
    reason: str = Field(description="viral_scoreをその値にした理由の説明")

    @field_validator("theme", "hook", "structure", "emotion", "cta", "target_reader", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
