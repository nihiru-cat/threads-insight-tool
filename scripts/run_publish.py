"""Publish all approved-and-unposted candidates to Threads, unattended.

Unlike the Streamlit "Threads投稿" page (which always requires a human to
click a button per post), this script publishes every currently-approved
candidate without further confirmation — the kind of thing you might put on
a cron schedule. Because of that, it refuses to run at all unless
AUTO_POST=true is set in .env, so unattended posting is always an explicit
opt-in rather than the default.

Usage:
    python scripts/run_publish.py --limit 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Running this file directly puts `scripts/` on sys.path, not the project
# root — add the root so `app.*` imports resolve regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.logging_config import setup_logging
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.services.publishing_service import run_publish_batch
from app.services.threads_client import ThreadsClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()

    if not settings.auto_post:
        print(
            "AUTO_POST=false のため、このスクリプトは実行できません。\n"
            "無人での投稿を意図的に許可する場合のみ、.envで AUTO_POST=true を設定してください。\n"
            "人が確認しながら投稿する場合はStreamlitの「Threads投稿」画面を使用してください。"
        )
        sys.exit(1)

    secrets = [settings.threads_access_token, settings.openai_api_key, settings.anthropic_api_key]
    logger = setup_logging(settings.log_dir, settings.log_level, secrets=secrets)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    if not settings.threads_access_token or not settings.threads_user_id:
        print("THREADS_ACCESS_TOKEN / THREADS_USER_ID が.envに設定されていません。")
        sys.exit(1)

    with session_scope(session_factory) as session:
        rows = GeneratedPostRepository(session).list_publishable(limit=args.limit)
        if not rows:
            print("投稿待ち（承認済み・未投稿）の候補はありません。")
            return

    with ThreadsClient(
        access_token=settings.threads_access_token,
        base_url=settings.threads_api_base_url,
        timeout_seconds=settings.threads_api_timeout_seconds,
        max_retries=settings.threads_api_max_retries,
        backoff_base_seconds=settings.threads_api_backoff_base_seconds,
        logger=logger,
    ) as client:
        with session_scope(session_factory) as session:
            results = run_publish_batch(
                client, session, rows, settings.threads_user_id, settings.threads_publish_wait_seconds, logger=logger
            )

    for r in results:
        status = f"threads_post_id={r.threads_post_id} permalink={r.permalink}" if r.ok else f"ERROR: {r.error}"
        print(f"generated_post_id={r.generated_post_id}: {status}")


if __name__ == "__main__":
    main()
