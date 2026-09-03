from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.analysis import PostAnalysisResult
from tests.conftest import save_post, valid_analysis_payload


def test_upsert_creates_new_analysis(db_session):
    post = save_post(db_session, "1")
    repo = AnalysisRepository(db_session)
    result = PostAnalysisResult.model_validate(valid_analysis_payload())

    saved = repo.upsert(post.id, result, ai_provider="anthropic", ai_model="claude-sonnet-5")

    assert saved.post_id == post.id
    assert saved.viral_score == 72
    assert repo.count_analyzed() == 1


def test_upsert_overwrites_existing_analysis_for_same_post(db_session):
    post = save_post(db_session, "1")
    repo = AnalysisRepository(db_session)
    first = PostAnalysisResult.model_validate(valid_analysis_payload(viral_score=40))
    second = PostAnalysisResult.model_validate(valid_analysis_payload(viral_score=90))

    repo.upsert(post.id, first, ai_provider="anthropic", ai_model="claude-sonnet-5")
    repo.upsert(post.id, second, ai_provider="anthropic", ai_model="claude-sonnet-5")

    assert repo.count_analyzed() == 1
    assert repo.get_by_post_id(post.id).viral_score == 90


def test_list_unanalyzed_posts_excludes_analyzed(db_session):
    post1 = save_post(db_session, "1")
    save_post(db_session, "2")
    repo = AnalysisRepository(db_session)
    repo.upsert(
        post1.id, PostAnalysisResult.model_validate(valid_analysis_payload()), ai_provider="anthropic", ai_model="m"
    )

    unanalyzed = repo.list_unanalyzed_posts()
    assert [p.thread_id for p in unanalyzed] == ["2"]


def test_list_analyzed_filters_by_min_viral_score(db_session):
    post1 = save_post(db_session, "1")
    post2 = save_post(db_session, "2")
    repo = AnalysisRepository(db_session)
    repo.upsert(
        post1.id,
        PostAnalysisResult.model_validate(valid_analysis_payload(viral_score=30)),
        ai_provider="a",
        ai_model="m",
    )
    repo.upsert(
        post2.id,
        PostAnalysisResult.model_validate(valid_analysis_payload(viral_score=85)),
        ai_provider="a",
        ai_model="m",
    )

    high_only = repo.list_analyzed(min_viral_score=70)
    assert [post.thread_id for post, _ in high_only] == ["2"]

    all_analyzed = repo.list_analyzed()
    assert len(all_analyzed) == 2
    # sorted by viral_score desc
    assert [post.thread_id for post, _ in all_analyzed] == ["2", "1"]
