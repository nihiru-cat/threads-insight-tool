from app.exceptions import ThreadsRateLimitError
from app.repositories.post_repository import PostRepository
from app.services.search_service import run_search_batch, run_search_job
from tests.conftest import make_post


class FakeClient:
    def __init__(self, posts=None, error=None):
        self._posts = posts or []
        self._error = error
        self.calls = []

    def search(self, keyword, search_type, limit=25):
        self.calls.append((keyword, search_type, limit))
        if self._error:
            raise self._error
        return self._posts


def test_run_search_job_saves_posts_and_reports_counts(db_session):
    client = FakeClient(posts=[make_post("1"), make_post("2")])

    result = run_search_job(client, db_session, keyword="占い", search_type="TOP")

    assert result.ok
    assert result.fetched == 2
    assert result.saved == 2
    assert result.duplicates == 0
    assert PostRepository(db_session).total_count() == 2


def test_run_search_job_handles_api_error_without_raising(db_session):
    client = FakeClient(error=ThreadsRateLimitError("rate limited"))

    result = run_search_job(client, db_session, keyword="占い", search_type="TOP")

    assert not result.ok
    assert "rate limited" in result.error
    assert PostRepository(db_session).total_count() == 0


def test_run_search_batch_covers_all_keyword_search_type_pairs(db_session):
    client = FakeClient(posts=[make_post("1")])

    results = run_search_batch(client, db_session, keywords=["占い", "開運"], search_types=["TOP", "RECENT"])

    assert len(results) == 4
    assert client.calls == [
        ("占い", "TOP", 25),
        ("占い", "RECENT", 25),
        ("開運", "TOP", 25),
        ("開運", "RECENT", 25),
    ]
