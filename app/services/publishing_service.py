"""Orchestrates publishing an approved generated post to Threads.

Only rows with status="approved" are ever attempted — human approval
(Phase 4) is an unconditional prerequisite, not something AUTO_POST can
bypass. A successful publish moves the row to status="posted" via
GeneratedPostRepository.mark_published; since list_publishable only returns
"approved" rows, a posted row can never be picked up again by a later batch
run. This status transition IS the double-post guard — there is no separate
"already posted" flag that could drift out of sync with it.

AUTO_POST does not change what this module does. It gates *how* publishing
gets invoked: the Streamlit UI's per-item button always requires an
explicit human click regardless of AUTO_POST; scripts/run_publish.py
additionally refuses to run at all unless AUTO_POST=true, since that script
could be put on a cron schedule and become the "fully automatic" posting
path the spec says must not be the default.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.exceptions import PostSaveError, ThreadsAPIError
from app.models.generated_post import GeneratedPost
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.services.threads_client import ThreadsClient


@dataclass
class PublishJobResult:
    generated_post_id: int
    threads_post_id: str | None = None
    permalink: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def publish_generated_post(
    client: ThreadsClient,
    session: Session,
    row: GeneratedPost,
    threads_user_id: str,
    wait_seconds: float,
    logger: logging.Logger | None = None,
) -> PublishJobResult:
    """Publish one approved candidate to Threads. Never raises.

    Refuses (without calling the API) if `row.status != "approved"` — this
    is a defensive re-check; callers are expected to only pass rows from
    GeneratedPostRepository.list_publishable(), which already filters this.
    """
    log = logger or logging.getLogger("threads_tool")

    if row.status != "approved":
        msg = f"generated_post_id={row.id} is not approved (status={row.status!r}) — refusing to publish"
        log.error(msg)
        return PublishJobResult(generated_post_id=row.id, error=msg)

    log.info("Threads投稿開始: generated_post_id=%s", row.id)
    try:
        published = client.publish_post(threads_user_id, row.generated_text, wait_seconds=wait_seconds)
    except ThreadsAPIError as exc:
        log.error("Threads投稿失敗: generated_post_id=%s error=%s", row.id, exc)
        return PublishJobResult(generated_post_id=row.id, error=str(exc))

    # The post is live on Threads at this point — client.publish_post only
    # raises before this if the post was never actually created. A failure
    # recording that fact below must not be reported as an ordinary error:
    # doing so would invite a retry that posts the same text again.
    try:
        GeneratedPostRepository(session).mark_published(
            row.id, published.threads_post_id, published.permalink, dt.datetime.now(dt.timezone.utc)
        )
    except PostSaveError as exc:
        log.critical(
            "Threads投稿には成功しましたが、DBへの記録に失敗しました。手動での修正が必要です: "
            "generated_post_id=%s threads_post_id=%s error=%s",
            row.id,
            published.threads_post_id,
            exc,
        )
        return PublishJobResult(
            generated_post_id=row.id,
            threads_post_id=published.threads_post_id,
            permalink=published.permalink,
            error=(
                f"投稿は成功しましたが記録に失敗しました（threads_post_id={published.threads_post_id}）。"
                "このままでは再投稿すると重複します。手動でDBを確認してください。"
            ),
        )

    log.info("Threads投稿完了: generated_post_id=%s threads_post_id=%s", row.id, published.threads_post_id)
    return PublishJobResult(
        generated_post_id=row.id, threads_post_id=published.threads_post_id, permalink=published.permalink
    )


def run_publish_batch(
    client: ThreadsClient,
    session: Session,
    rows: list[GeneratedPost],
    threads_user_id: str,
    wait_seconds: float,
    logger: logging.Logger | None = None,
) -> list[PublishJobResult]:
    return [
        publish_generated_post(client, session, row, threads_user_id, wait_seconds, logger=logger) for row in rows
    ]
