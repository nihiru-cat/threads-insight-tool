"""Persistence layer for Post rows: dedup-safe saves + dashboard/listing queries."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.exceptions import PostSaveError
from app.models.post import Post
from app.schemas.post import ThreadsSearchPost


class SaveResult(NamedTuple):
    saved: int
    duplicates: int


@dataclass
class PostFilter:
    keyword: str | None = None
    search_type: str | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None


class PostRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_posts(
        self,
        posts: list[ThreadsSearchPost],
        keyword: str,
        search_type: str,
        fetched_at: dt.datetime,
    ) -> SaveResult:
        if not posts:
            return SaveResult(saved=0, duplicates=0)

        incoming_ids = [p.id for p in posts]
        existing_ids = set(
            self._session.execute(
                select(Post.thread_id).where(Post.thread_id.in_(incoming_ids))
            ).scalars()
        )

        saved = 0
        duplicates = 0
        try:
            for post in posts:
                if post.id in existing_ids:
                    duplicates += 1
                    continue
                self._session.add(
                    Post(
                        thread_id=post.id,
                        username=post.username,
                        text=post.text,
                        timestamp=post.timestamp,
                        permalink=post.permalink,
                        keyword=keyword,
                        search_type=search_type,
                        fetched_at=fetched_at,
                    )
                )
                existing_ids.add(post.id)  # guard against dupes within the same batch
                saved += 1
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise PostSaveError(f"Failed to save posts for keyword={keyword!r}: {exc}") from exc

        return SaveResult(saved=saved, duplicates=duplicates)

    # --- Dashboard / listing queries -------------------------------------------------

    def total_count(self) -> int:
        return self._session.execute(select(func.count(Post.id))).scalar_one()

    def count_since(self, since: dt.datetime) -> int:
        return self._session.execute(
            select(func.count(Post.id)).where(Post.fetched_at >= since)
        ).scalar_one()

    def count_by_keyword(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Post.keyword, func.count(Post.id)).group_by(Post.keyword)
        ).all()
        return {keyword: count for keyword, count in rows}

    def count_by_search_type(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Post.search_type, func.count(Post.id)).group_by(Post.search_type)
        ).all()
        return {search_type: count for search_type, count in rows}

    def list_posts(self, post_filter: PostFilter | None = None, limit: int = 500) -> list[Post]:
        stmt = select(Post).order_by(Post.timestamp.desc().nulls_last())
        post_filter = post_filter or PostFilter()

        if post_filter.keyword:
            stmt = stmt.where(Post.keyword == post_filter.keyword)
        if post_filter.search_type:
            stmt = stmt.where(Post.search_type == post_filter.search_type)
        if post_filter.date_from:
            stmt = stmt.where(func.date(Post.fetched_at) >= post_filter.date_from.isoformat())
        if post_filter.date_to:
            stmt = stmt.where(func.date(Post.fetched_at) <= post_filter.date_to.isoformat())

        stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars())
