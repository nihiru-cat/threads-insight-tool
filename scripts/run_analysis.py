"""Run AI analysis over unanalyzed posts from the command line.

Usage:
    python scripts/run_analysis.py --limit 10
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
from app.repositories.analysis_repository import AnalysisRepository
from app.services.ai.factory import get_ai_client
from app.services.analysis_service import run_analysis_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()
    secrets = [settings.threads_access_token, settings.openai_api_key, settings.anthropic_api_key]
    logger = setup_logging(settings.log_dir, settings.log_level, secrets=secrets)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    ai_model = settings.openai_model if settings.ai_provider == "openai" else settings.anthropic_model

    with get_ai_client(settings, logger=logger) as client:
        with session_scope(session_factory) as session:
            posts = AnalysisRepository(session).list_unanalyzed_posts(limit=args.limit)
            if not posts:
                print("未分析の投稿はありません。")
                return
            results = run_analysis_batch(client, session, posts, settings.ai_provider, ai_model, logger=logger)

    for r in results:
        status = f"viral_score={r.viral_score}" if r.ok else f"ERROR: {r.error}"
        print(f"post_id={r.post_id}: {status}")


if __name__ == "__main__":
    main()
