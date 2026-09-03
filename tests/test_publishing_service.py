import datetime as dt

import pytest

from app.exceptions import PostSaveError, ThreadsRateLimitError
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.services.publishing_service import publish_generated_post, run_publish_batch
from app.services.threads_client import PublishedPost
from tests.conftest import save_post


class FakePublishClient:
    """`results`, when given, yields a distinct PublishedPost per call (like
    real Threads media ids would be distinct) — a single fixed `result` is
    fine for single-call tests but would collide with the unique
    threads_post_id constraint if reused across multiple rows."""

    def __init__(self, result=None, results=None, error=None):
        self._result = result
        self._results = list(results) if results is not None else None
        self._error = error
        self.calls = []

    def publish_post(self, threads_user_id, text, wait_seconds=30.0):
        self.calls.append((threads_user_id, text, wait_seconds))
        if self._error:
            raise self._error
        if self._results is not None:
            return self._results.pop(0)
        return self._result


def make_approved_row(session, post_id="1", text="投稿文"):
    post = save_post(session, post_id)
    return GeneratedPostRepository(session).create(
        source_post_id=post.id, status="approved", generated_text=text, attempt_count=1, ai_provider="a", ai_model="m"
    )


def test_publish_generated_post_success_marks_posted(db_session):
    row = make_approved_row(db_session)
    client = FakePublishClient(result=PublishedPost(threads_post_id="media-1", permalink="https://t/@u/media-1"))

    result = publish_generated_post(client, db_session, row, threads_user_id="12345", wait_seconds=0)

    assert result.ok
    assert result.threads_post_id == "media-1"
    assert result.permalink == "https://t/@u/media-1"
    saved = GeneratedPostRepository(db_session).get_by_id(row.id)
    assert saved.status == "posted"
    assert saved.threads_post_id == "media-1"
    assert saved.published_at is not None
    assert client.calls == [("12345", "投稿文", 0)]


def test_publish_generated_post_refuses_non_approved_status(db_session):
    post = save_post(db_session, "1")
    row = GeneratedPostRepository(db_session).create(
        source_post_id=post.id, status="candidate", generated_text="x", attempt_count=1, ai_provider="a", ai_model="m"
    )
    client = FakePublishClient(result=PublishedPost(threads_post_id="media-1", permalink=None))

    result = publish_generated_post(client, db_session, row, threads_user_id="12345", wait_seconds=0)

    assert not result.ok
    assert "not approved" in result.error
    assert client.calls == []  # never called the API
    assert GeneratedPostRepository(db_session).get_by_id(row.id).status == "candidate"


def test_publish_generated_post_api_error_leaves_row_approved_for_retry(db_session):
    row = make_approved_row(db_session)
    client = FakePublishClient(error=ThreadsRateLimitError("rate limited"))

    result = publish_generated_post(client, db_session, row, threads_user_id="12345", wait_seconds=0)

    assert not result.ok
    assert "rate limited" in result.error
    saved = GeneratedPostRepository(db_session).get_by_id(row.id)
    assert saved.status == "approved"  # still publishable — safe to retry, nothing was posted
    assert saved.threads_post_id is None


def test_publish_generated_post_db_failure_after_success_reports_error_but_not_silent(db_session, monkeypatch):
    row = make_approved_row(db_session)
    client = FakePublishClient(result=PublishedPost(threads_post_id="media-1", permalink=None))

    def broken_mark_published(self, *args, **kwargs):
        raise PostSaveError("disk full")

    monkeypatch.setattr(GeneratedPostRepository, "mark_published", broken_mark_published)

    result = publish_generated_post(client, db_session, row, threads_user_id="12345", wait_seconds=0)

    assert not result.ok
    # The real Threads post id must still surface even though saving it failed,
    # so a human reviewing the error has what they need to fix the DB by hand.
    assert result.threads_post_id == "media-1"
    assert "media-1" in result.error


def test_run_publish_batch_covers_all_rows(db_session):
    row1 = make_approved_row(db_session, post_id="1", text="text1")
    row2 = make_approved_row(db_session, post_id="2", text="text2")
    client = FakePublishClient(
        results=[
            PublishedPost(threads_post_id="media-1", permalink=None),
            PublishedPost(threads_post_id="media-2", permalink=None),
        ]
    )

    results = run_publish_batch(client, db_session, [row1, row2], threads_user_id="12345", wait_seconds=0)

    assert len(results) == 2
    assert all(r.ok for r in results)
    assert len(client.calls) == 2
