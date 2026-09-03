"""Run a keyword search from the command line (useful for testing without Streamlit).

Usage:
    python scripts/run_search.py --keyword 占い --search-type TOP
    python scripts/run_search.py --all-active-keywords --search-type TOP RECENT
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
from app.repositories.keyword_repository import KeywordRepository
from app.services.search_service import run_search_batch
from app.services.threads_client import ThreadsClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--all-active-keywords", action="store_true")
    parser.add_argument("--search-type", nargs="+", default=["TOP"], choices=["TOP", "RECENT"])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    settings = get_settings()
    logger = setup_logging(settings.log_dir, settings.log_level, secrets=[settings.threads_access_token])
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_scope(session_factory) as session:
        keyword_repo = KeywordRepository(session)
        keyword_repo.seed_defaults()
        keywords = args.keyword or [kw.keyword for kw in keyword_repo.list_active()]

    with ThreadsClient(
        access_token=settings.threads_access_token,
        base_url=settings.threads_api_base_url,
        timeout_seconds=settings.threads_api_timeout_seconds,
        max_retries=settings.threads_api_max_retries,
        backoff_base_seconds=settings.threads_api_backoff_base_seconds,
        logger=logger,
    ) as client:
        with session_scope(session_factory) as session:
            results = run_search_batch(client, session, keywords, args.search_type, limit=args.limit, logger=logger)

    for r in results:
        status = "OK" if r.ok else f"ERROR: {r.error}"
        print(f"[{r.search_type}] {r.keyword}: fetched={r.fetched} saved={r.saved} duplicates={r.duplicates} {status}")


if __name__ == "__main__":
    main()
