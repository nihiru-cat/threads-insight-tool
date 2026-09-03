import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.exceptions import AIInvalidResponseError, AIRateLimitError
from app.services.ai.json_utils import call_and_validate, extract_json
from tests.conftest import FakeAIClient


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: int


def test_extract_json_strips_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_handles_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_call_and_validate_returns_parsed_model_on_success():
    client = FakeAIClient(responses=[json.dumps({"a": 1})])
    result = call_and_validate(client, "sys", "user", _Schema)
    assert result.a == 1
    assert client.calls == 1


def test_call_and_validate_retries_invalid_json_then_succeeds():
    client = FakeAIClient(responses=["not json", json.dumps({"a": 1})])
    result = call_and_validate(client, "sys", "user", _Schema, max_parse_retries=2)
    assert result.a == 1
    assert client.calls == 2


def test_call_and_validate_retries_schema_violation_then_succeeds():
    client = FakeAIClient(responses=[json.dumps({"a": "not an int"}), json.dumps({"a": 1})])
    result = call_and_validate(client, "sys", "user", _Schema, max_parse_retries=2)
    assert result.a == 1


def test_call_and_validate_raises_after_exhausting_retries():
    client = FakeAIClient(responses=["not json", "still not json", "nope"])
    with pytest.raises(AIInvalidResponseError):
        call_and_validate(client, "sys", "user", _Schema, max_parse_retries=2)
    assert client.calls == 3


def test_call_and_validate_propagates_network_errors_immediately():
    client = FakeAIClient(error=AIRateLimitError("rate limited"))
    with pytest.raises(AIRateLimitError):
        call_and_validate(client, "sys", "user", _Schema, max_parse_retries=2)
    assert client.calls == 1
