import datetime as dt

import pytest

from app.db import init_db, make_engine, make_session_factory
from app.schemas.post import ThreadsSearchPost


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_post(post_id: str, text: str = "hello", username: str = "user1") -> ThreadsSearchPost:
    return ThreadsSearchPost(
        id=post_id,
        text=text,
        timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        permalink=f"https://www.threads.net/@{username}/post/{post_id}",
        username=username,
        media_type="TEXT",
        has_replies=False,
        is_quote_post=False,
        is_reply=False,
    )


def save_post(session, post_id: str, text: str = "hello", keyword: str = "占い"):
    """Insert a Post row (via the real repository, so dedup/columns match prod) and return it."""
    from app.repositories.post_repository import PostRepository

    PostRepository(session).save_posts(
        [make_post(post_id, text=text)],
        keyword=keyword,
        search_type="TOP",
        fetched_at=dt.datetime.now(dt.timezone.utc),
    )
    from app.models.post import Post
    from sqlalchemy import select

    return session.execute(select(Post).where(Post.thread_id == post_id)).scalar_one()


def valid_analysis_payload(**overrides) -> dict:
    payload = {
        "theme": "復縁",
        "hook": "断定型の警告: このままだと後悔します",
        "structure": "結論先出し→理由→具体例→CTA",
        "emotion": "不安",
        "cta": "保存を促す",
        "target_reader": "復縁を望む20-30代女性",
        "viral_score": 72,
        "reason": "フックが強く、コメントを誘発しやすい構成のため",
    }
    payload.update(overrides)
    return payload


def save_analysis(session, post, **overrides):
    """Insert a PostAnalysis row (via the real repository) for `post` and return it."""
    from app.repositories.analysis_repository import AnalysisRepository
    from app.schemas.analysis import PostAnalysisResult

    result = PostAnalysisResult.model_validate(valid_analysis_payload(**overrides))
    return AnalysisRepository(session).upsert(post.id, result, ai_provider="anthropic", ai_model="claude-sonnet-5")


def valid_safety_payload(**overrides) -> dict:
    payload = {
        "is_safe": True,
        "violations": [],
        "reason": "問題のある表現は見当たりません",
    }
    payload.update(overrides)
    return payload


class FakeAIClient:
    """Test double for AIClient: returns queued responses, or raises a fixed
    error on every call, regardless of the prompts passed in."""

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self._responses = list(responses or [])
        self._error = error
        self.calls = 0

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self._error:
            raise self._error
        return self._responses.pop(0)

    def close(self) -> None:
        pass


class FakeSimilarityChecker:
    """Test double for SimilarityChecker: returns a fixed score, or scores from
    a queue (one per call) when `scores` is given, regardless of input text."""

    backend_name = "fake"

    def __init__(self, score: float = 0.0, scores: list[float] | None = None):
        self._score = score
        self._scores = list(scores) if scores is not None else None
        self.calls: list[tuple[str, str]] = []

    def similarity(self, text_a: str, text_b: str) -> float:
        self.calls.append((text_a, text_b))
        if self._scores is not None:
            return self._scores.pop(0) if self._scores else self._score
        return self._score

    def close(self) -> None:
        pass
