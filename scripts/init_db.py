"""Create tables (if missing) and seed the default keyword list.

Usage: python scripts/init_db.py
"""

import sys
from pathlib import Path

# Running this file directly puts `scripts/` on sys.path, not the project
# root — add the root so `app.*` imports resolve regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.repositories.keyword_repository import KeywordRepository


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        KeywordRepository(session).seed_defaults()
    print(f"DB initialized at {settings.database_path}")


if __name__ == "__main__":
    main()
