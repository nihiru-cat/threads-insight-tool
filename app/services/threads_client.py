"""HTTP client for the Threads API: `keyword_search` (Phase 1) and the
content-publishing endpoints (Phase 5).

keyword_search reference: https://developers.facebook.com/docs/threads/keyword-search/
    GET https://graph.threads.net/v1.0/keyword_search
    params: q, search_type (TOP|RECENT), search_mode (KEYWORD|TAG),
            media_type, since, until, limit, author_username, fields,
            access_token
    Requires the `threads_basic` and `threads_keyword_search` permissions.

Publishing reference: https://developers.facebook.com/docs/threads/posts
(two-step container model, same as Instagram's Graph API):
    1. POST /v1.0/{threads-user-id}/threads
       params: media_type=TEXT, text, access_token -> {"id": "<container_id>"}
    2. Wait ~30s for the container to finish processing (documented
       recommendation — there is no documented "ready" status to poll).
    3. POST /v1.0/{threads-user-id}/threads_publish
       params: creation_id=<container_id>, access_token -> {"id": "<media_id>"}
    Permalink is not returned by threads_publish, so it's fetched separately:
       GET /v1.0/{media_id}?fields=permalink&access_token=...
    Requires the `threads_basic` and `threads_content_publish` permissions.
    Rate limit: 250 published posts per rolling 24-hour period (per profile).

Only documented fields/parameters are used anywhere in this client. No field
is invented to fill in for data the API does not expose (e.g. like_count for
other users' posts is not available via keyword_search and is never
requested).

TODO(threads-api): pagination via a `paging.cursors.after` token is standard
for Graph-API-family endpoints but is not confirmed in the keyword_search
docs used to build this client. If/when confirmed, extend `search()` to
follow `paging.next` instead of relying on a single `limit`-sized page.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from app.exceptions import (
    ThreadsAPIError,
    ThreadsAuthError,
    ThreadsBadRequestError,
    ThreadsInvalidResponseError,
    ThreadsRateLimitError,
    ThreadsServerError,
    ThreadsTimeoutError,
)
from app.schemas.post import ThreadsSearchPost, ThreadsSearchResponse

SearchType = Literal["TOP", "RECENT"]

# Fields requested from keyword_search — documented ones only.
FIELDS = "id,text,timestamp,permalink,username,media_type,has_replies,is_quote_post,is_reply"

# Recommended wait between creating a media container and publishing it, so
# Meta has time to process/validate it first (documented recommendation,
# not a value we invented).
DEFAULT_PUBLISH_WAIT_SECONDS = 30.0


@dataclass
class PublishedPost:
    threads_post_id: str
    permalink: str | None


class ThreadsClient:
    def __init__(
        self,
        access_token: str,
        base_url: str = "https://graph.threads.net/v1.0",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        logger: logging.Logger | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not access_token:
            raise ThreadsAuthError("THREADS_ACCESS_TOKEN is not set")
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._logger = logger or logging.getLogger("threads_tool")
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "ThreadsClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- Phase 1: keyword_search ---------------------------------------------------

    def search(
        self,
        keyword: str,
        search_type: SearchType = "TOP",
        limit: int = 25,
    ) -> list[ThreadsSearchPost]:
        """Run one `keyword_search` call and return validated posts.

        Raises a ThreadsAPIError subclass on unrecoverable failure. Transient
        errors (timeout, 429, 5xx) are retried with exponential backoff up
        to `max_retries` times before raising.
        """
        params = {
            "q": keyword,
            "search_type": search_type,
            "fields": FIELDS,
            "limit": limit,
            "access_token": self._access_token,
        }
        url = f"{self._base_url}/keyword_search"
        response = self._request_with_retry("GET", url, params, context=f"keyword_search keyword={keyword!r}")
        payload = self._parse_json(response, context=f"keyword_search keyword={keyword!r}")

        try:
            parsed = ThreadsSearchResponse.model_validate(payload)
        except Exception as exc:  # pydantic ValidationError
            raise ThreadsInvalidResponseError(
                f"Unexpected response shape for keyword_search keyword={keyword!r}: {exc}"
            ) from exc
        return parsed.data

    # --- Phase 5: publishing ---------------------------------------------------

    def create_container(self, threads_user_id: str, text: str) -> str:
        """Step 1 of publishing: create a TEXT media container. Returns the
        container id (to pass as `creation_id` to publish_container)."""
        params = {"media_type": "TEXT", "text": text, "access_token": self._access_token}
        url = f"{self._base_url}/{threads_user_id}/threads"
        context = f"create_container user_id={threads_user_id}"
        response = self._request_with_retry("POST", url, params, context=context)
        payload = self._parse_json(response, context=context)
        container_id = payload.get("id")
        if not container_id:
            raise ThreadsInvalidResponseError(f"{context}: response missing 'id': {payload}")
        return str(container_id)

    def publish_container(self, threads_user_id: str, creation_id: str) -> str:
        """Step 2 of publishing: publish a previously created container.
        Returns the published post's Threads media id."""
        params = {"creation_id": creation_id, "access_token": self._access_token}
        url = f"{self._base_url}/{threads_user_id}/threads_publish"
        context = f"publish_container user_id={threads_user_id} creation_id={creation_id}"
        response = self._request_with_retry("POST", url, params, context=context)
        payload = self._parse_json(response, context=context)
        media_id = payload.get("id")
        if not media_id:
            raise ThreadsInvalidResponseError(f"{context}: response missing 'id': {payload}")
        return str(media_id)

    def get_permalink(self, media_id: str) -> str | None:
        """Fetch the permalink of an already-published post."""
        params = {"fields": "permalink", "access_token": self._access_token}
        url = f"{self._base_url}/{media_id}"
        context = f"get_permalink media_id={media_id}"
        response = self._request_with_retry("GET", url, params, context=context)
        payload = self._parse_json(response, context=context)
        return payload.get("permalink")

    def publish_post(
        self,
        threads_user_id: str,
        text: str,
        wait_seconds: float = DEFAULT_PUBLISH_WAIT_SECONDS,
    ) -> PublishedPost:
        """Full publish flow: create container -> wait -> publish -> fetch permalink.

        Raises a ThreadsAPIError subclass if the post itself was not
        published (failure in create_container or publish_container — each
        already retries transient errors internally). Once publish_container
        has returned a media id, the post IS live on Threads, so a failure
        fetching its permalink afterward is logged and swallowed rather than
        raised — treating it as a full failure here would tell a caller to
        retry publishing, which would double-post. Callers that need the
        permalink and get None back can fetch it later via get_permalink().
        """
        container_id = self.create_container(threads_user_id, text)
        self._logger.info(
            "Threads投稿コンテナ作成完了 (container_id=%s)。%.0f秒待機してから公開します。", container_id, wait_seconds
        )
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        media_id = self.publish_container(threads_user_id, container_id)

        try:
            permalink = self.get_permalink(media_id)
        except ThreadsAPIError as exc:
            self._logger.warning(
                "投稿は公開されましたが、permalinkの取得に失敗しました (media_id=%s): %s", media_id, exc
            )
            permalink = None

        return PublishedPost(threads_post_id=media_id, permalink=permalink)

    # --- Shared request/retry/parse machinery -----------------------------------

    def _request_with_retry(self, method: str, url: str, params: dict, context: str) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                self._maybe_retry_or_raise(attempt, ThreadsTimeoutError(f"Request timed out for {context}: {exc}"))
                continue
            except httpx.HTTPError as exc:
                self._maybe_retry_or_raise(attempt, ThreadsServerError(f"Network error for {context}: {exc}"))
                continue

            error = self._error_for_status(response, context)
            if error is None:
                return response
            if isinstance(error, (ThreadsRateLimitError, ThreadsServerError)):
                self._maybe_retry_or_raise(attempt, error)
                continue
            raise error

    def _maybe_retry_or_raise(self, attempt: int, error: Exception) -> None:
        if attempt > self._max_retries:
            raise error
        delay = self._backoff_base_seconds * (2 ** (attempt - 1))
        self._logger.warning(
            "Threads API transient error (attempt %s/%s), retrying in %.1fs: %s",
            attempt,
            self._max_retries,
            delay,
            error,
        )
        time.sleep(delay)

    def _error_for_status(self, response: httpx.Response, context: str) -> Exception | None:
        status = response.status_code
        if status < 400:
            return None
        if status == 429:
            return ThreadsRateLimitError(f"Rate limited (429) for {context}")
        if status in (401, 403):
            return ThreadsAuthError(f"Auth error ({status}) for {context} — check access token/permissions")
        if 500 <= status < 600:
            return ThreadsServerError(f"Server error ({status}) for {context}")
        return ThreadsBadRequestError(f"Bad request ({status}) for {context}: {response.text[:500]}")

    def _parse_json(self, response: httpx.Response, context: str) -> dict:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ThreadsInvalidResponseError(f"Invalid JSON for {context}: {exc}") from exc
