"""Orchestrates: build prompt -> call AI provider -> validate JSON -> save.

Mirrors app.services.search_service in shape: each post is analyzed in
isolation, and API/validation failures are captured on the returned result
object rather than raised, so a batch run over many posts can't be aborted
by one bad response and can't crash the calling Streamlit app.

viral_score is explicitly NOT based on engagement metrics (like_count etc.)
because the Threads API does not expose them for other users' posts — the
prompt asks the model to score based on hook strength, theme fit, emotional
appeal, comment-inducing power, structural reusability, and how easily the
structure could be adapted into a new post.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.exceptions import AIError, PostSaveError
from app.models.post import Post
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.analysis import PostAnalysisResult
from app.services.ai.base import AIClient
from app.services.ai.json_utils import call_and_validate

SYSTEM_PROMPT = """\
あなたは占い・スピリチュアル系のThreads投稿を分析する専門アナリストです。
与えられた投稿本文から、以下の8項目を持つJSONオブジェクトを1つだけ出力してください。
説明文・前置き・Markdownのコードフェンスは一切付けず、JSONオブジェクトのみを出力してください。

フィールド定義:
- theme (string): 投稿の主題カテゴリ（例: 恋愛運, 金運, 自己啓発, 復縁 など）
- hook (string): 冒頭フックの型（例: 断定型の警告, 共感型の問いかけ, 意外性の提示 など）とその要約
- structure (string): 文章構成の型（例: 結論先出し→理由→具体例→CTA など）
- emotion (string): 訴求している主な感情（例: 不安, 希望, 好奇心, 焦り など）
- cta (string): 読者に促している行動の型（例: 保存を促す, コメントを促す, フォローを促す など。CTAが無ければ「なし」）
- target_reader (string): 想定読者層（例: 復縁を望む20-30代女性 など）
- viral_score (integer, 0-100): 伸びやすさの推定スコア。
  Threads APIではいいね数等のエンゲージメント指標を取得できないため、以下の観点から総合的に推定すること:
  フックの強さ / テーマ適合度 / 感情訴求の強さ / コメントを誘発する力 / 構成の再利用しやすさ / 新規投稿への展開しやすさ
- reason (string): viral_scoreをその値にした理由の説明（上記6観点のうちどれが強い/弱いか具体的に）

出力は必ず次のキーのみを持つJSONオブジェクトにしてください: theme, hook, structure, emotion, cta, target_reader, viral_score, reason
"""


def build_user_prompt(post: Post) -> str:
    return (
        f"検索キーワード: {post.keyword}\n"
        f"search_type: {post.search_type}\n"
        f"投稿本文:\n{post.text or '(本文なし)'}\n"
    )


@dataclass
class AnalysisJobResult:
    post_id: int
    viral_score: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def analyze_post(
    client: AIClient,
    session: Session,
    post: Post,
    ai_provider: str,
    ai_model: str,
    max_parse_retries: int = 2,
    logger: logging.Logger | None = None,
) -> AnalysisJobResult:
    """Analyze one post and persist the result. Never raises."""
    log = logger or logging.getLogger("threads_tool")
    log.info("AI分析開始: post_id=%s keyword=%s", post.id, post.keyword)

    user_prompt = build_user_prompt(post)

    try:
        result = call_and_validate(
            client,
            SYSTEM_PROMPT,
            user_prompt,
            PostAnalysisResult,
            max_parse_retries=max_parse_retries,
            logger=log,
            log_context=f"post_id={post.id}",
        )
    except AIError as exc:
        log.error("AI分析失敗: post_id=%s error=%s", post.id, exc)
        return AnalysisJobResult(post_id=post.id, error=str(exc))

    try:
        AnalysisRepository(session).upsert(post.id, result, ai_provider=ai_provider, ai_model=ai_model)
    except PostSaveError as exc:
        log.error("DB保存エラー: post_id=%s error=%s", post.id, exc)
        return AnalysisJobResult(post_id=post.id, error=str(exc))

    log.info("AI分析完了: post_id=%s viral_score=%s", post.id, result.viral_score)
    return AnalysisJobResult(post_id=post.id, viral_score=result.viral_score)


def run_analysis_batch(
    client: AIClient,
    session: Session,
    posts: list[Post],
    ai_provider: str,
    ai_model: str,
    max_parse_retries: int = 2,
    logger: logging.Logger | None = None,
) -> list[AnalysisJobResult]:
    return [
        analyze_post(client, session, post, ai_provider, ai_model, max_parse_retries=max_parse_retries, logger=logger)
        for post in posts
    ]
