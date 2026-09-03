"""ORM model for an AI-generated original post candidate (Phase 3/4/5).

One row per generation *run* for a source post — a source post can be
regenerated later (e.g. after Phase 4 review), which creates another row
rather than overwriting the previous one, so history is preserved.

`status` is a plain string (not a DB-level enum/check constraint):
"candidate" / "manual_review" (set by app.services.generation_service),
"approved" / "rejected" (set by a human via the Streamlit review UI, Phase 4
— see app.repositories.generated_post_repository.set_status), "posted" (set
by app.services.publishing_service after a successful Threads publish,
Phase 5). Only "approved" rows are eligible to be posted — publishing moves
a row out of "approved", which is what prevents double-posting the same
candidate (see GeneratedPostRepository.list_publishable / mark_published).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GeneratedPost(Base):
    __tablename__ = "generated_posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Similarity to the source post's original text.
    string_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    semantic_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    similarity_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Highest similarity found against the pool of recently generated candidates
    # (mass-duplicate check), regardless of which source post they came from.
    duplicate_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_safe: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    safety_violations: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]
    safety_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Human-readable summary of why the final attempt still failed, when
    # status="manual_review". None when status="candidate".
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    ai_model: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    # When a human approved/rejected this candidate (Phase 4). None while
    # status is "candidate" or "manual_review".
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set only after a successful Threads publish (Phase 5) — status="posted".
    threads_post_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_permalink: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"GeneratedPost(source_post_id={self.source_post_id}, status={self.status!r})"
