"""Persistence layer for configurable search keywords."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.keyword import DEFAULT_KEYWORDS, Keyword


class KeywordRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def seed_defaults(self) -> None:
        """Insert the default keyword set, but only if the table is empty.

        Never overwrites user edits (added/removed keywords) on subsequent
        app startups.
        """
        has_any = self._session.execute(select(Keyword.id).limit(1)).first()
        if has_any:
            return
        for kw in DEFAULT_KEYWORDS:
            self._session.add(Keyword(keyword=kw, is_active=True))
        self._session.commit()

    def list_all(self) -> list[Keyword]:
        return list(self._session.execute(select(Keyword).order_by(Keyword.id)).scalars())

    def list_active(self) -> list[Keyword]:
        return list(
            self._session.execute(
                select(Keyword).where(Keyword.is_active.is_(True)).order_by(Keyword.id)
            ).scalars()
        )

    def add(self, keyword: str) -> Keyword:
        keyword = keyword.strip()
        existing = self._session.execute(
            select(Keyword).where(Keyword.keyword == keyword)
        ).scalar_one_or_none()
        if existing:
            existing.is_active = True
            self._session.commit()
            return existing
        kw = Keyword(keyword=keyword, is_active=True)
        self._session.add(kw)
        self._session.commit()
        return kw

    def set_active(self, keyword_id: int, is_active: bool) -> None:
        kw = self._session.get(Keyword, keyword_id)
        if kw is not None:
            kw.is_active = is_active
            self._session.commit()

    def delete(self, keyword_id: int) -> None:
        kw = self._session.get(Keyword, keyword_id)
        if kw is not None:
            self._session.delete(kw)
            self._session.commit()
