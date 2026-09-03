"""ORM model for configurable search keywords.

Keywords are stored in the DB (not hardcoded) so they can be added/removed
later from the Streamlit UI without a code change or redeploy.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Seeded into the `keywords` table on first `init_db()` if it's empty.
DEFAULT_KEYWORDS = [
    "占い",
    "スピリチュアル",
    "引き寄せ",
    "復縁",
    "ツインレイ",
    "運気",
    "開運",
]


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Keyword(id={self.id}, keyword={self.keyword!r}, is_active={self.is_active})"
