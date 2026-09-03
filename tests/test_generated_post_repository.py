import datetime as dt

from app.repositories.generated_post_repository import GeneratedPostRepository
from tests.conftest import save_analysis, save_post


def test_create_and_list_by_status(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)

    repo.create(
        source_post_id=post.id,
        status="candidate",
        generated_text="生成された投稿文",
        attempt_count=1,
        ai_provider="anthropic",
        ai_model="claude-sonnet-5",
        string_similarity=0.1,
        semantic_similarity=0.2,
        similarity_backend="string",
        duplicate_similarity=0.0,
        is_safe=True,
        safety_violations=[],
        safety_reason="問題なし",
    )

    candidates = repo.list_by_status("candidate")
    assert len(candidates) == 1
    assert candidates[0].generated_text == "生成された投稿文"
    assert repo.count_by_status() == {"candidate": 1}


def test_create_manual_review_stores_rejection_reason(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)

    repo.create(
        source_post_id=post.id,
        status="manual_review",
        generated_text="却下された投稿文",
        attempt_count=4,
        ai_provider="anthropic",
        ai_model="claude-sonnet-5",
        safety_violations=["fear_mongering"],
        rejection_reason="安全性チェックに抵触",
    )

    rows = repo.list_by_status("manual_review")
    assert len(rows) == 1
    assert rows[0].rejection_reason == "安全性チェックに抵触"
    assert "fear_mongering" in rows[0].safety_violations


def test_list_recent_texts_orders_newest_first(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)
    for i in range(3):
        repo.create(
            source_post_id=post.id,
            status="candidate",
            generated_text=f"text-{i}",
            attempt_count=1,
            ai_provider="a",
            ai_model="m",
        )

    texts = repo.list_recent_texts(limit=2)
    assert texts == ["text-2", "text-1"]


def test_list_eligible_ungenerated_posts_filters_by_score_and_existing_generation(db_session):
    post_high = save_post(db_session, "1")
    post_low = save_post(db_session, "2")
    post_already_generated = save_post(db_session, "3")
    save_analysis(db_session, post_high, viral_score=85)
    save_analysis(db_session, post_low, viral_score=40)
    save_analysis(db_session, post_already_generated, viral_score=90)

    repo = GeneratedPostRepository(db_session)
    repo.create(
        source_post_id=post_already_generated.id,
        status="candidate",
        generated_text="x",
        attempt_count=1,
        ai_provider="a",
        ai_model="m",
    )

    eligible = repo.list_eligible_ungenerated_posts(min_viral_score=70)
    assert [p.thread_id for p in eligible] == ["1"]


def test_set_status_approves_and_stamps_reviewed_at(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)
    row = repo.create(
        source_post_id=post.id, status="candidate", generated_text="x", attempt_count=1, ai_provider="a", ai_model="m"
    )
    assert row.reviewed_at is None

    updated = repo.set_status(row.id, "approved")

    assert updated.status == "approved"
    assert updated.reviewed_at is not None
    assert repo.count_by_status() == {"approved": 1}


def test_set_status_rejects(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)
    row = repo.create(
        source_post_id=post.id, status="manual_review", generated_text="x", attempt_count=4, ai_provider="a", ai_model="m"
    )

    updated = repo.set_status(row.id, "rejected")

    assert updated.status == "rejected"
    assert repo.get_by_id(row.id).status == "rejected"


def test_set_status_returns_none_for_missing_row(db_session):
    repo = GeneratedPostRepository(db_session)
    assert repo.set_status(999, "approved") is None


def test_get_by_id_returns_none_for_missing_row(db_session):
    repo = GeneratedPostRepository(db_session)
    assert repo.get_by_id(999) is None


def test_list_publishable_returns_only_approved(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)
    candidate = repo.create(
        source_post_id=post.id, status="candidate", generated_text="x", attempt_count=1, ai_provider="a", ai_model="m"
    )
    approved = repo.create(
        source_post_id=post.id, status="approved", generated_text="y", attempt_count=1, ai_provider="a", ai_model="m"
    )

    publishable = repo.list_publishable()

    assert [row.id for row in publishable] == [approved.id]
    assert candidate.id not in [row.id for row in publishable]


def test_mark_published_sets_posted_status_and_details(db_session):
    post = save_post(db_session, "1")
    repo = GeneratedPostRepository(db_session)
    row = repo.create(
        source_post_id=post.id, status="approved", generated_text="x", attempt_count=1, ai_provider="a", ai_model="m"
    )
    now = dt.datetime.now(dt.timezone.utc)

    updated = repo.mark_published(row.id, "media-1", "https://www.threads.net/@u/post/media-1", now)

    assert updated.status == "posted"
    assert updated.threads_post_id == "media-1"
    assert updated.published_permalink == "https://www.threads.net/@u/post/media-1"
    assert updated.published_at == now
    # A posted row is no longer publishable — this is the double-post guard.
    assert repo.list_publishable() == []


def test_mark_published_returns_none_for_missing_row(db_session):
    repo = GeneratedPostRepository(db_session)
    assert repo.mark_published(999, "media-1", None, dt.datetime.now(dt.timezone.utc)) is None
