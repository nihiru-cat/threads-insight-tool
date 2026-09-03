import datetime as dt

from app.repositories.post_repository import PostFilter, PostRepository
from tests.conftest import make_post


def test_save_posts_persists_new_rows(db_session):
    repo = PostRepository(db_session)
    posts = [make_post("1"), make_post("2")]

    result = repo.save_posts(posts, keyword="占い", search_type="TOP", fetched_at=dt.datetime.now(dt.timezone.utc))

    assert result.saved == 2
    assert result.duplicates == 0
    assert repo.total_count() == 2


def test_save_posts_dedups_by_thread_id(db_session):
    repo = PostRepository(db_session)
    fetched_at = dt.datetime.now(dt.timezone.utc)

    first = repo.save_posts([make_post("1")], keyword="占い", search_type="TOP", fetched_at=fetched_at)
    second = repo.save_posts(
        [make_post("1"), make_post("2")], keyword="占い", search_type="RECENT", fetched_at=fetched_at
    )

    assert first.saved == 1
    assert second.saved == 1
    assert second.duplicates == 1
    assert repo.total_count() == 2


def test_save_posts_dedups_within_same_batch(db_session):
    repo = PostRepository(db_session)
    result = repo.save_posts(
        [make_post("1"), make_post("1")],
        keyword="占い",
        search_type="TOP",
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )

    assert result.saved == 1
    assert result.duplicates == 1
    assert repo.total_count() == 1


def test_list_posts_filters_by_keyword_and_search_type(db_session):
    repo = PostRepository(db_session)
    fetched_at = dt.datetime.now(dt.timezone.utc)
    repo.save_posts([make_post("1")], keyword="占い", search_type="TOP", fetched_at=fetched_at)
    repo.save_posts([make_post("2")], keyword="開運", search_type="RECENT", fetched_at=fetched_at)

    only_uranai = repo.list_posts(PostFilter(keyword="占い"))
    assert [p.thread_id for p in only_uranai] == ["1"]

    only_recent = repo.list_posts(PostFilter(search_type="RECENT"))
    assert [p.thread_id for p in only_recent] == ["2"]


def test_count_by_keyword_and_search_type(db_session):
    repo = PostRepository(db_session)
    fetched_at = dt.datetime.now(dt.timezone.utc)
    repo.save_posts([make_post("1")], keyword="占い", search_type="TOP", fetched_at=fetched_at)
    repo.save_posts([make_post("2")], keyword="占い", search_type="RECENT", fetched_at=fetched_at)

    assert repo.count_by_keyword() == {"占い": 2}
    assert repo.count_by_search_type() == {"TOP": 1, "RECENT": 1}
