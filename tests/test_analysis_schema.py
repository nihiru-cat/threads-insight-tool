import pytest
from pydantic import ValidationError

from app.schemas.analysis import PostAnalysisResult
from tests.conftest import valid_analysis_payload


def test_valid_payload_parses():
    result = PostAnalysisResult.model_validate(valid_analysis_payload())
    assert result.viral_score == 72
    assert result.theme == "復縁"


def test_rejects_missing_field():
    payload = valid_analysis_payload()
    del payload["cta"]
    with pytest.raises(ValidationError):
        PostAnalysisResult.model_validate(payload)


def test_rejects_extra_field():
    payload = valid_analysis_payload(unexpected_field="oops")
    with pytest.raises(ValidationError):
        PostAnalysisResult.model_validate(payload)


@pytest.mark.parametrize("score", [-1, 101, 1000])
def test_rejects_out_of_range_viral_score(score):
    payload = valid_analysis_payload(viral_score=score)
    with pytest.raises(ValidationError):
        PostAnalysisResult.model_validate(payload)


def test_rejects_blank_string_field():
    payload = valid_analysis_payload(theme="   ")
    with pytest.raises(ValidationError):
        PostAnalysisResult.model_validate(payload)


def test_rejects_wrong_type_for_viral_score():
    payload = valid_analysis_payload(viral_score="high")
    with pytest.raises(ValidationError):
        PostAnalysisResult.model_validate(payload)
