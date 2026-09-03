"""Persistence layer for AI-generated post analyses."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.exceptions import PostSaveError
from app.models.analysis import PostAnalysis
from app.models.post import Post
from app.schemas.analysis import PostAnalysisResult


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_post_id(self, post_id: int) -> PostAnalysis | None:
        return self._session.execute(
            select(PostAnalysis).where(PostAnalysis.post_id == post_id)
        ).scalar_one_or_none()

    def upsert(
        self,
        post_id: int,
        result: PostAnalysisResult,
        ai_provider: str,
        ai_model: str,
    ) -> PostAnalysis:
        """Insert a new analysis for `post_id`, or overwrite the existing one."""
        try:
            existing = self.get_by_post_id(post_id)
            now = dt.datetime.now(dt.timezone.utc)
            if existing is None:
                existing = PostAnalysis(post_id=post_id)
                self._session.add(existing)

            existing.theme = result.theme
            existing.hook = result.hook
            existing.structure = result.structure
            existing.emotion = result.emotion
            existing.cta = result.cta
            existing.target_reader = result.target_reader
            existing.viral_score = result.viral_score
            existing.reason = result.reason
            existing.ai_provider = ai_provider
            existing.ai_model = ai_model
            existing.updated_at = now

            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise PostSaveError(f"Failed to save analysis for post_id={post_id}: {exc}") from exc

        return existing

    # --- Queries -----------------------------------------------------------------

    def list_unanalyzed_posts(self, limit: int = 50) -> list[Post]:
        stmt = (
            select(Post)
            .outerjoin(PostAnalysis, PostAnalysis.post_id == Post.id)
            .where(PostAnalysis.id.is_(None))
            .order_by(Post.id)
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def count_analyzed(self) -> int:
        return self._session.execute(select(func.count(PostAnalysis.id))).scalar_one()

    def list_analyzed(self, min_viral_score: int | None = None, limit: int = 500) -> list[tuple[Post, PostAnalysis]]:
        stmt = select(Post, PostAnalysis).join(PostAnalysis, PostAnalysis.post_id == Post.id)
        if min_viral_score is not None:
            stmt = stmt.where(PostAnalysis.viral_score >= min_viral_score)
        stmt = stmt.order_by(PostAnalysis.viral_score.desc()).limit(limit)
        return [(post, analysis) for post, analysis in self._session.execute(stmt).all()]
