import json

from app.exceptions import AIRateLimitError
from app.repositories.analysis_repository import AnalysisRepository
from app.services.analysis_service import analyze_post, run_analysis_batch
from tests.conftest import FakeAIClient, save_post, valid_analysis_payload


def test_analyze_post_success_saves_result(db_session):
    post = save_post(db_session, "1")
    client = FakeAIClient(responses=[json.dumps(valid_analysis_payload())])

    result = analyze_post(client, db_session, post, ai_provider="anthropic", ai_model="claude-sonnet-5")

    assert result.ok
    assert result.viral_score == 72
    saved = AnalysisRepository(db_session).get_by_post_id(post.id)
    assert saved is not None
    assert saved.theme == "復縁"


def test_analyze_post_api_error_returns_error_without_raising(db_session):
    post = save_post(db_session, "1")
    client = FakeAIClient(error=AIRateLimitError("rate limited"))

    result = analyze_post(client, db_session, post, ai_provider="anthropic", ai_model="claude-sonnet-5")

    assert not result.ok
    assert "rate limited" in result.error
    assert AnalysisRepository(db_session).get_by_post_id(post.id) is None


def test_analyze_post_retries_invalid_json_then_succeeds(db_session):
    post = save_post(db_session, "1")
    client = FakeAIClient(responses=["not json at all", json.dumps(valid_analysis_payload())])

    result = analyze_post(
        client, db_session, post, ai_provider="anthropic", ai_model="claude-sonnet-5", max_parse_retries=2
    )

    assert result.ok
    assert client.calls == 2


def test_analyze_post_exhausts_retries_and_reports_error(db_session):
    post = save_post(db_session, "1")
    client = FakeAIClient(responses=["not json", "still not json", "nope"])

    result = analyze_post(
        client, db_session, post, ai_provider="anthropic", ai_model="claude-sonnet-5", max_parse_retries=2
    )

    assert not result.ok
    assert client.calls == 3
    assert AnalysisRepository(db_session).get_by_post_id(post.id) is None


def test_analyze_post_rejects_schema_violating_json(db_session):
    post = save_post(db_session, "1")
    bad_payload = valid_analysis_payload(viral_score=999)
    client = FakeAIClient(responses=[json.dumps(bad_payload)] * 3)

    result = analyze_post(
        client, db_session, post, ai_provider="anthropic", ai_model="claude-sonnet-5", max_parse_retries=2
    )

    assert not result.ok


def test_run_analysis_batch_covers_all_posts(db_session):
    post1 = save_post(db_session, "1")
    post2 = save_post(db_session, "2")
    client = FakeAIClient(responses=[json.dumps(valid_analysis_payload())] * 2)

    results = run_analysis_batch(client, db_session, [post1, post2], ai_provider="a", ai_model="m")

    assert len(results) == 2
    assert all(r.ok for r in results)
    assert AnalysisRepository(db_session).count_analyzed() == 2
