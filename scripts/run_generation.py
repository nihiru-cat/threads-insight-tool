"""Generate original posts from analyzed posts with a high viral_score.

Usage:
    python scripts/run_generation.py --limit 5
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
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.services.ai.factory import get_ai_client
from app.services.generation_service import run_generation_batch
from app.services.similarity.factory import get_similarity_checker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    settings = get_settings()
    secrets = [settings.threads_access_token, settings.openai_api_key, settings.anthropic_api_key]
    logger = setup_logging(settings.log_dir, settings.log_level, secrets=secrets)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    ai_model = settings.openai_model if settings.ai_provider == "openai" else settings.anthropic_model

    with session_scope(session_factory) as session:
        posts = GeneratedPostRepository(session).list_eligible_ungenerated_posts(
            min_viral_score=settings.generation_min_viral_score, limit=args.limit
        )
        if not posts:
            print(f"viral_score>={settings.generation_min_viral_score}の未生成投稿はありません。")
            return
        analysis_repo = AnalysisRepository(session)
        items = [(post, analysis_repo.get_by_post_id(post.id)) for post in posts]

    with get_ai_client(settings, logger=logger) as client, get_similarity_checker(settings, logger=logger) as sim:
        with session_scope(session_factory) as session:
            results = run_generation_batch(client, sim, session, items, settings, settings.ai_provider, ai_model, logger)

    for r in results:
        status = f"status={r.status} attempts={r.attempts}" if r.ok else f"ERROR: {r.error}"
        print(f"source_post_id={r.source_post_id}: {status}")


if __name__ == "__main__":
    main()
