"""ORM model for a fetched Threads post."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("thread_id", name="uq_posts_thread_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Threads API post id ("id" field from keyword_search). Unique -> dedup.
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Original post timestamp, as returned by the Threads API.
    timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    permalink: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Which search produced this row.
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    search_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # When our search job fetched this post from the API.
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When this row was inserted into the database.
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Post(id={self.id}, thread_id={self.thread_id!r}, keyword={self.keyword!r})"
