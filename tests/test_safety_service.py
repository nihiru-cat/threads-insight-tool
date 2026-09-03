import json

import pytest

from app.exceptions import AIInvalidResponseError, AIRateLimitError
from app.services.safety_service import check_safety
from tests.conftest import FakeAIClient, valid_safety_payload


def test_check_safety_returns_safe_result():
    client = FakeAIClient(responses=[json.dumps(valid_safety_payload())])
    result = check_safety(client, "問題のない投稿文")
    assert result.is_safe is True


def test_check_safety_returns_unsafe_result_with_violations():
    payload = valid_safety_payload(is_safe=False, violations=["exaggerated_guarantee"], reason="絶対に叶うと断定")
    client = FakeAIClient(responses=[json.dumps(payload)])
    result = check_safety(client, "絶対に願いが叶う方法")
    assert result.is_safe is False
    assert result.violations == ["exaggerated_guarantee"]


def test_check_safety_retries_invalid_json():
    client = FakeAIClient(responses=["not json", json.dumps(valid_safety_payload())])
    result = check_safety(client, "text", max_parse_retries=2)
    assert result.is_safe is True
    assert client.calls == 2


def test_check_safety_propagates_api_error():
    client = FakeAIClient(error=AIRateLimitError("rate limited"))
    with pytest.raises(AIRateLimitError):
        check_safety(client, "text")


def test_check_safety_raises_after_exhausting_parse_retries():
    client = FakeAIClient(responses=["nope", "still nope", "nope again"])
    with pytest.raises(AIInvalidResponseError):
        check_safety(client, "text", max_parse_retries=2)
