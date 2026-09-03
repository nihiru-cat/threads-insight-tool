"""Pydantic schema for the AI content-safety check on a generated post draft.

Covers the checks that need language understanding (personal attacks,
medical/legal/financial claims stated as fact, exaggerated guarantees,
fear-mongering). The other two checks from the spec — excessive similarity
to the source post, and mass-duplicate generation — are structural, not
semantic, and are handled by app.services.similarity instead (comparing
against the source text and against a pool of recently generated texts).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SafetyViolation = Literal[
    "personal_attack",
    "medical_legal_financial_claim",
    "exaggerated_guarantee",
    "fear_mongering",
]


class SafetyCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_safe: bool = Field(description="問題がなければtrue、いずれかの項目に抵触すればfalse")
    violations: list[SafetyViolation] = Field(
        default_factory=list,
        description="抵触した項目（is_safe=falseの場合は1件以上を記載。is_safe=trueなら空配列）",
    )
    reason: str = Field(description="判定理由の説明")
