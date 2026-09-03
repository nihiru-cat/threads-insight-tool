"""ORM model for AI-generated post analysis (Phase 2).

One row per Post (`post_id` is unique — a post is re-analyzed by
overwriting its existing row, not accumulating history).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PostAnalysis(Base):
    __tablename__ = "post_analyses"
    __table_args__ = (UniqueConstraint("post_id", name="uq_post_analyses_post_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)

    theme: Mapped[str] = mapped_column(String(255), nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=False)
    structure: Mapped[str] = mapped_column(Text, nullable=False)
    emotion: Mapped[str] = mapped_column(String(255), nullable=False)
    cta: Mapped[str] = mapped_column(Text, nullable=False)
    target_reader: Mapped[str] = mapped_column(Text, nullable=False)
    viral_score: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    ai_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"PostAnalysis(post_id={self.post_id}, viral_score={self.viral_score})"
