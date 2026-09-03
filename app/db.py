"""SQLAlchemy engine/session wiring."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args)

    if is_sqlite:
        # SQLite ignores FOREIGN KEY constraints (e.g. ON DELETE CASCADE for
        # post_analyses.post_id) unless explicitly enabled per connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine) -> None:
    # Import models so they register on Base.metadata before create_all.
    from app.models import analysis, generated_post, keyword, post  # noqa: F401

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
