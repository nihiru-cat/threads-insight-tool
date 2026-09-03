import pytest
from pydantic import ValidationError

from app.schemas.generation import GeneratedPostDraft


def test_valid_payload_parses():
    result = GeneratedPostDraft.model_validate({"generated_text": "今日から運気が変わる3つの習慣"})
    assert result.generated_text == "今日から運気が変わる3つの習慣"


def test_rejects_blank_text():
    with pytest.raises(ValidationError):
        GeneratedPostDraft.model_validate({"generated_text": "   "})


def test_rejects_missing_field():
    with pytest.raises(ValidationError):
        GeneratedPostDraft.model_validate({})


def test_rejects_extra_field():
    with pytest.raises(ValidationError):
        GeneratedPostDraft.model_validate({"generated_text": "text", "extra": "oops"})
