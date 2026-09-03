"""Persistence layer for AI-generated post candidates."""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.exceptions import PostSaveError
from app.models.analysis import PostAnalysis
from app.models.generated_post import GeneratedPost
from app.models.post import Post

# Statuses a human can still act on (approve/reject/regenerate) in the
# Streamlit review UI (Phase 4). "approved"/"rejected" are terminal.
REVIEWABLE_STATUSES = ("candidate", "manual_review")
DECISION_STATUSES = ("approved", "rejected")


class GeneratedPostRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        source_post_id: int,
        status: str,
        generated_text: str,
        attempt_count: int,
        ai_provider: str,
        ai_model: str,
        string_similarity: float | None = None,
        semantic_similarity: float | None = None,
        similarity_backend: str | None = None,
        duplicate_similarity: float | None = None,
        is_safe: bool | None = None,
        safety_violations: list[str] | None = None,
        safety_reason: str | None = None,
        rejection_reason: str | None = None,
    ) -> GeneratedPost:
        row = GeneratedPost(
            source_post_id=source_post_id,
            status=status,
            generated_text=generated_text,
            attempt_count=attempt_count,
            string_similarity=string_similarity,
            semantic_similarity=semantic_similarity,
            similarity_backend=similarity_backend,
            duplicate_similarity=duplicate_similarity,
            is_safe=is_safe,
            safety_violations=json.dumps(safety_violations, ensure_ascii=False) if safety_violations else None,
            safety_reason=safety_reason,
            rejection_reason=rejection_reason,
            ai_provider=ai_provider,
            ai_model=ai_model,
        )
        try:
            self._session.add(row)
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise PostSaveError(f"Failed to save generated post for source_post_id={source_post_id}: {exc}") from exc
        return row

    def set_status(self, generated_post_id: int, status: str) -> GeneratedPost | None:
        """Record a human decision (approve/reject) on a candidate.

        Returns None if no row with that id exists (e.g. it was deleted
        concurrently) instead of raising, so the UI can show a message
        rather than crash.
        """
        row = self._session.get(GeneratedPost, generated_post_id)
        if row is None:
            return None
        try:
            row.status = status
            row.reviewed_at = dt.datetime.now(dt.timezone.utc)
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise PostSaveError(f"Failed to update status for generated_post_id={generated_post_id}: {exc}") from exc
        return row

    def mark_published(
        self,
        generated_post_id: int,
        threads_post_id: str,
        published_permalink: str | None,
        published_at: dt.datetime,
    ) -> GeneratedPost | None:
        """Record a successful Threads publish and move the row out of
        "approved" (to "posted") — this transition is what prevents the same
        candidate from being published twice; see list_publishable.

        Returns None if no row with that id exists.
        """
        row = self._session.get(GeneratedPost, generated_post_id)
        if row is None:
            return None
        try:
            row.status = "posted"
            row.threads_post_id = threads_post_id
            row.published_permalink = published_permalink
            row.published_at = published_at
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise PostSaveError(
                f"Failed to record publish result for generated_post_id={generated_post_id}: {exc}"
            ) from exc
        return row

    # --- Queries -----------------------------------------------------------------

    def get_by_id(self, generated_post_id: int) -> GeneratedPost | None:
        return self._session.get(GeneratedPost, generated_post_id)

    def list_recent_texts(self, limit: int = 50) -> list[str]:
        """Most recently generated candidate texts, across all source posts and
        statuses — the comparison pool for the mass-duplicate check."""
        stmt = select(GeneratedPost.generated_text).order_by(GeneratedPost.id.desc()).limit(limit)
        return list(self._session.execute(stmt).scalars())

    def list_by_status(self, status: str | None = None, limit: int = 200) -> list[GeneratedPost]:
        stmt = select(GeneratedPost).order_by(GeneratedPost.id.desc())
        if status:
            stmt = stmt.where(GeneratedPost.status == status)
        stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars())

    def count_by_status(self) -> dict[str, int]:
        rows = self._session.execute(
            select(GeneratedPost.status, func.count(GeneratedPost.id)).group_by(GeneratedPost.status)
        ).all()
        return {status: count for status, count in rows}

    def list_publishable(self, limit: int = 50) -> list[GeneratedPost]:
        """Approved candidates not yet posted to Threads. Once a row is
        posted its status becomes "posted", so it naturally drops out of
        this list — this is the primary double-post guard."""
        return self.list_by_status("approved", limit=limit)

    def list_eligible_ungenerated_posts(self, min_viral_score: int, limit: int = 50) -> list[Post]:
        """Analyzed posts with viral_score >= min_viral_score that have no
        generation attempt yet at all."""
        generated_source_ids = select(GeneratedPost.source_post_id).distinct()
        stmt = (
            select(Post)
            .join(PostAnalysis, PostAnalysis.post_id == Post.id)
            .where(PostAnalysis.viral_score >= min_viral_score)
            .where(Post.id.not_in(generated_source_ids))
            .order_by(PostAnalysis.viral_score.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())
