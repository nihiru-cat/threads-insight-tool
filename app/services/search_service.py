"""Orchestrates: Threads API search -> validate -> save -> log.

Isolates errors per (keyword, search_type) job so one failure (bad token,
rate limit exhausted, DB error) does not abort the rest of a multi-keyword
run or crash the calling Streamlit app.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.exceptions import ThreadsToolError
from app.repositories.post_repository import PostRepository, SaveResult
from app.services.threads_client import SearchType, ThreadsClient


@dataclass
class SearchJobResult:
    keyword: str
    search_type: str
    fetched: int = 0
    saved: int = 0
    duplicates: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_search_job(
    client: ThreadsClient,
    session: Session,
    keyword: str,
    search_type: SearchType,
    limit: int = 25,
    logger: logging.Logger | None = None,
) -> SearchJobResult:
    """Run one keyword_search call and persist the results.

    Never raises — API/DB failures are captured on the returned
    SearchJobResult.error and logged, so a caller looping over many
    (keyword, search_type) pairs can keep going.
    """
    log = logger or logging.getLogger("threads_tool")
    log.info("検索開始: keyword=%s search_type=%s", keyword, search_type)

    try:
        posts = client.search(keyword=keyword, search_type=search_type, limit=limit)
    except ThreadsToolError as exc:
        log.error("APIエラー: keyword=%s search_type=%s error=%s", keyword, search_type, exc)
        return SearchJobResult(keyword=keyword, search_type=search_type, error=str(exc))

    fetched_at = dt.datetime.now(dt.timezone.utc)
    repo = PostRepository(session)
    try:
        result: SaveResult = repo.save_posts(posts, keyword=keyword, search_type=search_type, fetched_at=fetched_at)
    except ThreadsToolError as exc:
        log.error("DB保存エラー: keyword=%s search_type=%s error=%s", keyword, search_type, exc)
        return SearchJobResult(keyword=keyword, search_type=search_type, fetched=len(posts), error=str(exc))

    log.info(
        "検索完了: keyword=%s search_type=%s 取得件数=%s 新規保存件数=%s 重複件数=%s",
        keyword,
        search_type,
        len(posts),
        result.saved,
        result.duplicates,
    )
    return SearchJobResult(
        keyword=keyword,
        search_type=search_type,
        fetched=len(posts),
        saved=result.saved,
        duplicates=result.duplicates,
    )


def run_search_batch(
    client: ThreadsClient,
    session: Session,
    keywords: list[str],
    search_types: list[SearchType],
    limit: int = 25,
    logger: logging.Logger | None = None,
) -> list[SearchJobResult]:
    return [
        run_search_job(client, session, keyword, search_type, limit=limit, logger=logger)
        for keyword in keywords
        for search_type in search_types
    ]
