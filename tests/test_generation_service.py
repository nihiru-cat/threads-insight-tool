import json

from app.config.settings import Settings
from app.exceptions import AIRateLimitError
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.services.generation_service import generate_post, run_generation_batch
from tests.conftest import FakeAIClient, FakeSimilarityChecker, save_analysis, save_post, valid_safety_payload


def _draft(text: str = "生成された全く新しい投稿文") -> str:
    return json.dumps({"generated_text": text})


def _safety(is_safe: bool = True, violations=None, reason: str = "問題なし") -> str:
    return json.dumps(valid_safety_payload(is_safe=is_safe, violations=violations or [], reason=reason))


def make_settings(**overrides) -> Settings:
    defaults = dict(
        generation_max_regenerations=3,
        semantic_similarity_reject_threshold=0.80,
        duplicate_similarity_reject_threshold=0.80,
        ai_max_parse_retries=2,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_generate_post_success_first_attempt_saves_candidate(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    client = FakeAIClient(responses=[_draft(), _safety()])
    similarity = FakeSimilarityChecker(score=0.1)

    result = generate_post(client, similarity, db_session, post, analysis, make_settings(), "anthropic", "m")

    assert result.ok
    assert result.status == "candidate"
    assert result.attempts == 1
    rows = GeneratedPostRepository(db_session).list_by_status("candidate")
    assert len(rows) == 1
    assert rows[0].semantic_similarity == 0.1


def test_generate_post_regenerates_on_high_source_similarity_then_succeeds(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    client = FakeAIClient(responses=[_draft("draft1"), _safety(), _draft("draft2"), _safety()])
    similarity = FakeSimilarityChecker(scores=[0.9, 0.1])

    result = generate_post(client, similarity, db_session, post, analysis, make_settings(), "anthropic", "m")

    assert result.ok
    assert result.status == "candidate"
    assert result.attempts == 2
    saved = GeneratedPostRepository(db_session).list_by_status("candidate")[0]
    assert saved.generated_text == "draft2"


def test_generate_post_exhausts_regenerations_and_saves_manual_review(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    # 2 total attempts (1 initial + 1 regeneration), each consuming draft+safety.
    client = FakeAIClient(responses=[_draft(), _safety(), _draft(), _safety()])
    similarity = FakeSimilarityChecker(score=0.9)  # always "too similar"

    settings = make_settings(generation_max_regenerations=1)
    result = generate_post(client, similarity, db_session, post, analysis, settings, "anthropic", "m")

    assert result.ok  # manual_review is an expected outcome, not an error
    assert result.status == "manual_review"
    assert result.attempts == 2
    rows = GeneratedPostRepository(db_session).list_by_status("manual_review")
    assert len(rows) == 1
    assert "semantic_similarity" in rows[0].rejection_reason


def test_generate_post_rejects_on_safety_violation_then_regenerates(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    client = FakeAIClient(
        responses=[
            _draft("draft1"),
            _safety(is_safe=False, violations=["fear_mongering"], reason="不安を過度に煽っています"),
            _draft("draft2"),
            _safety(),
        ]
    )
    similarity = FakeSimilarityChecker(score=0.1)

    result = generate_post(client, similarity, db_session, post, analysis, make_settings(), "anthropic", "m")

    assert result.ok
    assert result.status == "candidate"
    assert result.attempts == 2
    saved = GeneratedPostRepository(db_session).list_by_status("candidate")[0]
    assert saved.generated_text == "draft2"


def test_generate_post_api_error_returns_error_immediately(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    client = FakeAIClient(error=AIRateLimitError("rate limited"))
    similarity = FakeSimilarityChecker(score=0.0)

    result = generate_post(client, similarity, db_session, post, analysis, make_settings(), "anthropic", "m")

    assert not result.ok
    assert "rate limited" in result.error
    assert GeneratedPostRepository(db_session).count_by_status() == {}


def test_generate_post_rejects_on_duplicate_similarity_then_regenerates(db_session):
    post = save_post(db_session, "1")
    analysis = save_analysis(db_session, post)
    # Seed one existing generated post so the duplicate-check pool is non-empty.
    GeneratedPostRepository(db_session).create(
        source_post_id=post.id,
        status="candidate",
        generated_text="既存の生成済み投稿文",
        attempt_count=1,
        ai_provider="a",
        ai_model="m",
    )

    client = FakeAIClient(responses=[_draft("draft1"), _safety(), _draft("draft2"), _safety()])
    # attempt1: semantic=0.1 (pass), duplicate=0.9 (reject) -> regenerate
    # attempt2: semantic=0.1 (pass), duplicate=0.1 (pass) -> success
    similarity = FakeSimilarityChecker(scores=[0.1, 0.9, 0.1, 0.1])

    result = generate_post(client, similarity, db_session, post, analysis, make_settings(), "anthropic", "m")

    assert result.ok
    assert result.status == "candidate"
    assert result.attempts == 2


def test_run_generation_batch_covers_all_items(db_session):
    post1 = save_post(db_session, "1")
    post2 = save_post(db_session, "2")
    analysis1 = save_analysis(db_session, post1)
    analysis2 = save_analysis(db_session, post2)
    client = FakeAIClient(responses=[_draft(), _safety(), _draft(), _safety()])
    similarity = FakeSimilarityChecker(score=0.1)

    results = run_generation_batch(
        client, similarity, db_session, [(post1, analysis1), (post2, analysis2)], make_settings(), "anthropic", "m"
    )

    assert len(results) == 2
    assert all(r.ok and r.status == "candidate" for r in results)
