import pytest
from pydantic import ValidationError

from app.schemas.safety import SafetyCheckResult
from tests.conftest import valid_safety_payload


def test_valid_safe_payload_parses():
    result = SafetyCheckResult.model_validate(valid_safety_payload())
    assert result.is_safe is True
    assert result.violations == []


def test_valid_unsafe_payload_parses():
    payload = valid_safety_payload(is_safe=False, violations=["fear_mongering"], reason="不安を過度に煽っています")
    result = SafetyCheckResult.model_validate(payload)
    assert result.is_safe is False
    assert result.violations == ["fear_mongering"]


def test_rejects_unknown_violation_value():
    payload = valid_safety_payload(is_safe=False, violations=["not_a_real_violation"])
    with pytest.raises(ValidationError):
        SafetyCheckResult.model_validate(payload)


def test_rejects_missing_field():
    payload = valid_safety_payload()
    del payload["reason"]
    with pytest.raises(ValidationError):
        SafetyCheckResult.model_validate(payload)


def test_rejects_extra_field():
    payload = valid_safety_payload(unexpected="oops")
    with pytest.raises(ValidationError):
        SafetyCheckResult.model_validate(payload)
