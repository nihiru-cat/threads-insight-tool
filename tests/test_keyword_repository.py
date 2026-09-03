from app.models.keyword import DEFAULT_KEYWORDS
from app.repositories.keyword_repository import KeywordRepository


def test_seed_defaults_populates_empty_table(db_session):
    repo = KeywordRepository(db_session)
    repo.seed_defaults()

    assert sorted(kw.keyword for kw in repo.list_all()) == sorted(DEFAULT_KEYWORDS)


def test_seed_defaults_is_noop_if_already_seeded(db_session):
    repo = KeywordRepository(db_session)
    repo.seed_defaults()
    repo.add("追加キーワード")
    repo.seed_defaults()

    assert len(repo.list_all()) == len(DEFAULT_KEYWORDS) + 1


def test_add_and_deactivate_keyword(db_session):
    repo = KeywordRepository(db_session)
    kw = repo.add("新キーワード")

    assert kw.is_active is True
    assert [k.keyword for k in repo.list_active()] == ["新キーワード"]

    repo.set_active(kw.id, False)
    assert repo.list_active() == []
    assert [k.keyword for k in repo.list_all()] == ["新キーワード"]


def test_delete_keyword(db_session):
    repo = KeywordRepository(db_session)
    kw = repo.add("削除対象")
    repo.delete(kw.id)

    assert repo.list_all() == []
