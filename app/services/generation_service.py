"""Orchestrates original post generation: build prompt -> generate -> check -> save.

Copy-prevention is structural, not just instructional: the prompt built here
(see SYSTEM_PROMPT / build_user_prompt) is constructed ONLY from the source
post's AI analysis (theme/hook/structure/cta/target_reader — all abstracted
categories) and NEVER includes the source post's actual text. The model
literally cannot copy or paraphrase text it was never shown.

As a second, independent line of defense (in case the model's training data
happens to recall something similar anyway), each draft is checked against:
  1. semantic_similarity to the source post's text (app.services.similarity)
  2. duplicate_similarity to a pool of recently generated candidates, to
     catch mass-duplicate generation across different source posts
  3. an AI safety check (app.services.safety_service) for personal attacks,
     medical/legal/financial claims stated as fact, exaggerated guarantees,
     and fear-mongering

A draft that fails any of these is discarded and regenerated, up to
`generation_max_regenerations` additional attempts (config: Settings). If
every attempt fails, the last draft is saved with status="manual_review" and
a `rejection_reason` explaining why, for a human to review later (Phase 4) —
it is never silently discarded and never auto-approved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.exceptions import AIError, PostSaveError
from app.models.analysis import PostAnalysis
from app.models.post import Post
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.schemas.generation import GeneratedPostDraft
from app.services.ai.base import AIClient
from app.services.ai.json_utils import call_and_validate
from app.services.safety_service import check_safety
from app.services.similarity.base import SimilarityChecker
from app.services.similarity.string_similarity import StringSimilarityChecker

SYSTEM_PROMPT = """\
あなたは占い・スピリチュアル系のThreads投稿を書くオリジナルコンテンツライターです。
以下に渡されるのは、過去に伸びた投稿から抽出した「抽象化された型」の情報のみです。
（元投稿の本文そのものは一切渡されていません。）

この型の情報だけを参考に、完全にオリジナルな新しいThreads投稿を1つ書いてください。

厳守事項:
- 元投稿の文章・特定の言い回し・フレーズは一切知らないものとして書くこと（実際に渡されていません）
- 単純な言い換えではなく、新しい切り口・新しい具体例で書くこと
- 参考にしてよいのは、テーマカテゴリ・フックの型・構成の型・CTAの型のみです
- 医療・法律・金融について断定的な助言をしないこと
- 「絶対に」「100%」等の科学的根拠のない誇大な断定表現を使わないこと
- 読者の不安を過度に煽らないこと
- 特定個人への攻撃・誹謗中傷を含まないこと

出力は次のキーのみを持つJSONオブジェクトにしてください: generated_text
説明文・前置き・Markdownのコードフェンスは一切付けず、JSONオブジェクトのみを出力してください。
"""


def build_user_prompt(analysis: PostAnalysis) -> str:
    return (
        "以下の型を参考に、新しいオリジナル投稿を書いてください。\n"
        f"テーマカテゴリ: {analysis.theme}\n"
        f"フックの型: {analysis.hook}\n"
        f"文章構成の型: {analysis.structure}\n"
        f"訴求する感情: {analysis.emotion}\n"
        f"CTAの型: {analysis.cta}\n"
        f"想定読者層: {analysis.target_reader}\n"
    )


@dataclass
class GenerationJobResult:
    source_post_id: int
    status: str | None = None  # "candidate" or "manual_review"
    generated_post_id: int | None = None
    attempts: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def generate_post(
    client: AIClient,
    similarity_checker: SimilarityChecker,
    session: Session,
    post: Post,
    analysis: PostAnalysis,
    settings: Settings,
    ai_provider: str,
    ai_model: str,
    logger: logging.Logger | None = None,
) -> GenerationJobResult:
    """Generate (and check, and save) one original post candidate for `post`.

    Never raises for expected failure modes (rejected drafts end up as
    status="manual_review"); only unexpected AI/DB errors set `.error`.
    """
    log = logger or logging.getLogger("threads_tool")
    log.info("投稿生成開始: source_post_id=%s viral_score=%s", post.id, analysis.viral_score)

    string_checker = StringSimilarityChecker()
    user_prompt = build_user_prompt(analysis)
    source_text = post.text or ""

    duplicate_pool = GeneratedPostRepository(session).list_recent_texts(limit=settings.duplicate_check_pool_size)

    max_attempts = settings.generation_max_regenerations + 1
    last_draft_text = ""
    last_string_sim = 0.0
    last_semantic_sim = 0.0
    last_dup_sim = 0.0
    last_is_safe: bool | None = None
    last_violations: list[str] = []
    last_safety_reason = ""
    last_reasons: list[str] = []

    for attempt in range(1, max_attempts + 1):
        try:
            draft = call_and_validate(
                client,
                SYSTEM_PROMPT,
                user_prompt,
                GeneratedPostDraft,
                max_parse_retries=settings.ai_max_parse_retries,
                logger=log,
                log_context=f"source_post_id={post.id} generate attempt={attempt}",
            )
            safety = check_safety(
                client,
                draft.generated_text,
                max_parse_retries=settings.ai_max_parse_retries,
                logger=log,
                log_context=f"source_post_id={post.id} safety attempt={attempt}",
            )
        except AIError as exc:
            log.error("投稿生成失敗(APIエラー): source_post_id=%s error=%s", post.id, exc)
            return GenerationJobResult(source_post_id=post.id, attempts=attempt, error=str(exc))

        string_sim = string_checker.similarity(draft.generated_text, source_text)
        semantic_sim = similarity_checker.similarity(draft.generated_text, source_text)
        dup_sim = max(
            (similarity_checker.similarity(draft.generated_text, other) for other in duplicate_pool),
            default=0.0,
        )

        reasons = []
        if semantic_sim >= settings.semantic_similarity_reject_threshold:
            reasons.append(
                f"元投稿との意味的類似度が高すぎます (semantic_similarity={semantic_sim:.2f} "
                f">= {settings.semantic_similarity_reject_threshold})"
            )
        if dup_sim >= settings.duplicate_similarity_reject_threshold:
            reasons.append(
                f"既存の生成済み投稿と酷似しています (duplicate_similarity={dup_sim:.2f} "
                f">= {settings.duplicate_similarity_reject_threshold})"
            )
        if not safety.is_safe:
            reasons.append(f"安全性チェックに抵触: {', '.join(safety.violations)} — {safety.reason}")

        last_draft_text = draft.generated_text
        last_string_sim, last_semantic_sim, last_dup_sim = string_sim, semantic_sim, dup_sim
        last_is_safe, last_violations, last_safety_reason = safety.is_safe, list(safety.violations), safety.reason
        last_reasons = reasons

        if not reasons:
            try:
                row = GeneratedPostRepository(session).create(
                    source_post_id=post.id,
                    status="candidate",
                    generated_text=draft.generated_text,
                    attempt_count=attempt,
                    ai_provider=ai_provider,
                    ai_model=ai_model,
                    string_similarity=string_sim,
                    semantic_similarity=semantic_sim,
                    similarity_backend=similarity_checker.backend_name,
                    duplicate_similarity=dup_sim,
                    is_safe=safety.is_safe,
                    safety_violations=safety.violations,
                    safety_reason=safety.reason,
                )
            except PostSaveError as exc:
                log.error("DB保存エラー: source_post_id=%s error=%s", post.id, exc)
                return GenerationJobResult(source_post_id=post.id, attempts=attempt, error=str(exc))

            log.info("投稿生成完了: source_post_id=%s attempt=%s status=candidate", post.id, attempt)
            return GenerationJobResult(
                source_post_id=post.id, status="candidate", generated_post_id=row.id, attempts=attempt
            )

        log.warning(
            "投稿案を却下し再生成します: source_post_id=%s attempt=%s/%s reasons=%s",
            post.id,
            attempt,
            max_attempts,
            reasons,
        )

    try:
        row = GeneratedPostRepository(session).create(
            source_post_id=post.id,
            status="manual_review",
            generated_text=last_draft_text,
            attempt_count=max_attempts,
            ai_provider=ai_provider,
            ai_model=ai_model,
            string_similarity=last_string_sim,
            semantic_similarity=last_semantic_sim,
            similarity_backend=similarity_checker.backend_name,
            duplicate_similarity=last_dup_sim,
            is_safe=last_is_safe,
            safety_violations=last_violations,
            safety_reason=last_safety_reason,
            rejection_reason="; ".join(last_reasons),
        )
    except PostSaveError as exc:
        log.error("DB保存エラー: source_post_id=%s error=%s", post.id, exc)
        return GenerationJobResult(source_post_id=post.id, attempts=max_attempts, error=str(exc))

    log.warning("投稿生成: manual_review行き: source_post_id=%s attempts=%s", post.id, max_attempts)
    return GenerationJobResult(
        source_post_id=post.id, status="manual_review", generated_post_id=row.id, attempts=max_attempts
    )


def run_generation_batch(
    client: AIClient,
    similarity_checker: SimilarityChecker,
    session: Session,
    items: list[tuple[Post, PostAnalysis]],
    settings: Settings,
    ai_provider: str,
    ai_model: str,
    logger: logging.Logger | None = None,
) -> list[GenerationJobResult]:
    return [
        generate_post(client, similarity_checker, session, post, analysis, settings, ai_provider, ai_model, logger)
        for post, analysis in items
    ]
