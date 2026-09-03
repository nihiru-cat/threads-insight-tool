"""Pydantic schemas for validating Threads `keyword_search` API responses.

Only fields documented at
https://developers.facebook.com/docs/threads/keyword-search/ are modeled
here. In particular, no engagement metric (e.g. like_count) is documented as
available for other users' posts via this endpoint, so none is requested or
parsed — see ThreadsClient.FIELDS. Do not add fields here on guesswork; if
the Threads API adds a new documented field, add it explicitly with a
comment linking the doc section that confirms it.

TODO(threads-api): The `keyword_search` docs describe response fields only
via examples, not an exhaustive schema reference (unlike Graph API node
references). If a field appears in real API responses that is not listed
below, verify it against current official docs before relying on it instead
of silently accepting/ignoring it.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, field_validator


class ThreadsSearchPost(BaseModel):
    """One post object as returned inside `keyword_search`'s `data` array."""

    model_config = ConfigDict(extra="ignore")

    id: str
    text: str | None = None
    timestamp: dt.datetime | None = None
    permalink: str | None = None
    username: str | None = None
    media_type: str | None = None
    has_replies: bool | None = None
    is_quote_post: bool | None = None
    is_reply: bool | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_timestamp(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, dt.datetime):
            return value
        # Threads API returns ISO-8601, e.g. "2024-05-09T20:14:38+0000".
        return dt.datetime.fromisoformat(str(value))


class ThreadsSearchResponse(BaseModel):
    """Top-level `keyword_search` response envelope."""

    model_config = ConfigDict(extra="ignore")

    data: list[ThreadsSearchPost] = []
