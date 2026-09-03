"""Streamlit admin app: Dashboard / Posts / Search & Keywords / AI分析 / 投稿生成 / Threads投稿.

Run with: streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# `streamlit run app/ui/streamlit_app.py` puts this file's own directory on
# sys.path, not the project root — add the root so `app.*` imports resolve
# regardless of the working directory the command was launched from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.config import get_settings
from app.db import init_db, make_engine, make_session_factory, session_scope
from app.exceptions import ThreadsToolError
from app.logging_config import setup_logging
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.generated_post_repository import GeneratedPostRepository
from app.repositories.keyword_repository import KeywordRepository
from app.repositories.post_repository import PostFilter, PostRepository
from app.services.ai.factory import get_ai_client
from app.services.analysis_service import run_analysis_batch
from app.services.generation_service import generate_post, run_generation_batch
from app.services.publishing_service import publish_generated_post
from app.services.search_service import run_search_batch
from app.services.similarity.factory import get_similarity_checker
from app.services.threads_client import ThreadsClient

st.set_page_config(page_title="Threads Insight Tool", layout="wide")


@st.cache_resource
def bootstrap():
    settings = get_settings()
    logger = setup_logging(settings.log_dir, settings.log_level, secrets=[settings.threads_access_token])
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_scope(session_factory) as session:
        KeywordRepository(session).seed_defaults()
    return settings, logger, session_factory


settings, logger, session_factory = bootstrap()


def render_dashboard() -> None:
    st.header("Dashboard")
    with session_scope(session_factory) as session:
        repo = PostRepository(session)
        total = repo.total_count()
        today_start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = repo.count_since(today_start)
        by_keyword = repo.count_by_keyword()
        by_search_type = repo.count_by_search_type()

    col1, col2 = st.columns(2)
    col1.metric("DB保存投稿数", total)
    col2.metric("本日取得件数 (UTC)", today_count)

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("キーワード別件数")
        if by_keyword:
            st.bar_chart(by_keyword)
        else:
            st.caption("データがありません")
    with col4:
        st.subheader("TOP / RECENT別件数")
        if by_search_type:
            st.bar_chart(by_search_type)
        else:
            st.caption("データがありません")


def render_posts() -> None:
    st.header("Posts")
    with session_scope(session_factory) as session:
        keyword_options = ["すべて"] + [kw.keyword for kw in KeywordRepository(session).list_all()]

    col1, col2, col3, col4 = st.columns(4)
    keyword = col1.selectbox("キーワード", keyword_options)
    search_type = col2.selectbox("search_type", ["すべて", "TOP", "RECENT"])
    date_from = col3.date_input("開始日", value=None)
    date_to = col4.date_input("終了日", value=None)

    post_filter = PostFilter(
        keyword=None if keyword == "すべて" else keyword,
        search_type=None if search_type == "すべて" else search_type,
        date_from=date_from or None,
        date_to=date_to or None,
    )

    with session_scope(session_factory) as session:
        posts = PostRepository(session).list_posts(post_filter)
        rows = [
            {
                "timestamp": p.timestamp,
                "keyword": p.keyword,
                "search_type": p.search_type,
                "username": p.username,
                "text": p.text,
                "permalink": p.permalink,
            }
            for p in posts
        ]

    st.caption(f"{len(rows)} 件")
    st.dataframe(
        rows,
        column_config={"permalink": st.column_config.LinkColumn("permalink")},
        width="stretch",
        hide_index=True,
    )


def render_search_and_keywords() -> None:
    st.header("検索実行 / キーワード管理")

    st.subheader("キーワード管理")
    with session_scope(session_factory) as session:
        keywords = KeywordRepository(session).list_all()
        for kw in keywords:
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(kw.keyword)
            active = c2.checkbox("有効", value=kw.is_active, key=f"active_{kw.id}")
            if active != kw.is_active:
                KeywordRepository(session).set_active(kw.id, active)
                st.rerun()
            if c3.button("削除", key=f"delete_{kw.id}"):
                KeywordRepository(session).delete(kw.id)
                st.rerun()

    new_keyword = st.text_input("新規キーワード追加")
    if st.button("追加") and new_keyword.strip():
        with session_scope(session_factory) as session:
            KeywordRepository(session).add(new_keyword.strip())
        st.rerun()

    st.divider()
    st.subheader("検索実行")

    if not settings.threads_access_token:
        st.warning(".envにTHREADS_ACCESS_TOKENが設定されていません。検索は実行できません。")
        return

    with session_scope(session_factory) as session:
        active_keywords = [kw.keyword for kw in KeywordRepository(session).list_active()]

    selected_keywords = st.multiselect("検索キーワード", active_keywords, default=active_keywords)
    selected_types = st.multiselect("search_type", ["TOP", "RECENT"], default=["TOP", "RECENT"])
    limit = st.slider("1回あたりの取得件数 (limit)", min_value=1, max_value=100, value=settings.threads_api_search_limit)

    if st.button("検索実行", type="primary") and selected_keywords and selected_types:
        try:
            client = ThreadsClient(
                access_token=settings.threads_access_token,
                base_url=settings.threads_api_base_url,
                timeout_seconds=settings.threads_api_timeout_seconds,
                max_retries=settings.threads_api_max_retries,
                backoff_base_seconds=settings.threads_api_backoff_base_seconds,
                logger=logger,
            )
        except ThreadsToolError as exc:
            st.error(f"Threads APIクライアントの初期化に失敗しました: {exc}")
            return

        with st.spinner("検索中..."):
            with session_scope(session_factory) as session:
                results = run_search_batch(
                    client, session, selected_keywords, selected_types, limit=limit, logger=logger
                )
        client.close()

        for r in results:
            if r.ok:
                st.success(
                    f"[{r.search_type}] {r.keyword}: 取得={r.fetched} 新規保存={r.saved} 重複={r.duplicates}"
                )
            else:
                st.error(f"[{r.search_type}] {r.keyword}: エラー — {r.error}")


def _configured_ai_api_key() -> str:
    if settings.ai_provider.strip().lower() == "openai":
        return settings.openai_api_key
    return settings.anthropic_api_key


def render_analysis() -> None:
    st.header("AI分析")

    with session_scope(session_factory) as session:
        total_posts = PostRepository(session).total_count()
        analyzed_count = AnalysisRepository(session).count_analyzed()

    col1, col2, col3 = st.columns(3)
    col1.metric("総投稿数", total_posts)
    col2.metric("分析済み", analyzed_count)
    col3.metric("未分析", total_posts - analyzed_count)

    st.caption(f"AIプロバイダ: {settings.ai_provider}")

    if not _configured_ai_api_key():
        st.warning(
            f".envに{'OPENAI_API_KEY' if settings.ai_provider == 'openai' else 'ANTHROPIC_API_KEY'}"
            "が設定されていません。分析は実行できません。"
        )
    else:
        max_unanalyzed = max(total_posts - analyzed_count, 0)
        if max_unanalyzed == 0:
            st.info("未分析の投稿はありません。")
        else:
            if max_unanalyzed == 1:
                limit = 1
                st.caption("未分析の投稿は1件です。")
            else:
                limit = st.slider(
                    "分析する件数",
                    min_value=1,
                    max_value=max_unanalyzed,
                    value=min(10, max_unanalyzed),
                )

            if st.button("未分析の投稿を分析する", type="primary"):
                try:
                    client = get_ai_client(settings, logger=logger)
                except ThreadsToolError as exc:
                    st.error(f"AIクライアントの初期化に失敗しました: {exc}")
                    client = None

                if client is not None:
                    ai_model = settings.openai_model if settings.ai_provider == "openai" else settings.anthropic_model
                    with st.spinner("分析中..."):
                        with session_scope(session_factory) as session:
                            posts = AnalysisRepository(session).list_unanalyzed_posts(limit=limit)
                            results = run_analysis_batch(
                                client, session, posts, settings.ai_provider, ai_model, logger=logger
                            )
                    client.close()

                    ok_count = sum(1 for r in results if r.ok)
                    st.success(f"{ok_count}/{len(results)} 件の分析が完了しました（画面上部の件数は次の操作で更新されます）")
                    for r in results:
                        if not r.ok:
                            st.error(f"post_id={r.post_id}: {r.error}")

    st.divider()
    st.subheader("分析結果")
    min_score = st.slider("viral_score の下限で絞り込み", min_value=0, max_value=100, value=0)
    with session_scope(session_factory) as session:
        analyzed = AnalysisRepository(session).list_analyzed(min_viral_score=min_score or None)

    st.caption(f"{len(analyzed)} 件")
    for post, analysis in analyzed:
        with st.expander(f"[{analysis.viral_score}点] {post.keyword} / {post.username or '(unknown)'}"):
            st.markdown("**元投稿**")
            st.write(post.text)
            if post.permalink:
                st.markdown(f"[元投稿を開く]({post.permalink})")
            st.markdown("**AI分析**")
            st.json(
                {
                    "theme": analysis.theme,
                    "hook": analysis.hook,
                    "structure": analysis.structure,
                    "emotion": analysis.emotion,
                    "cta": analysis.cta,
                    "target_reader": analysis.target_reader,
                    "viral_score": analysis.viral_score,
                    "reason": analysis.reason,
                }
            )


def render_generation() -> None:
    st.header("投稿生成")
    st.caption(
        f"viral_score が {settings.generation_min_viral_score} 点以上の分析済み投稿から、"
        "オリジナルの投稿案を生成します（元投稿の文章は生成AIに一切渡されません）。"
    )

    with session_scope(session_factory) as session:
        status_counts = GeneratedPostRepository(session).count_by_status()
        eligible = GeneratedPostRepository(session).list_eligible_ungenerated_posts(
            min_viral_score=settings.generation_min_viral_score, limit=1000
        )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("生成候補 (candidate)", status_counts.get("candidate", 0))
    col2.metric("要確認 (manual_review)", status_counts.get("manual_review", 0))
    col3.metric("承認済み (approved)", status_counts.get("approved", 0))
    col4.metric("却下済み (rejected)", status_counts.get("rejected", 0))
    col5.metric("生成対象（未生成）", len(eligible))

    st.caption(f"AIプロバイダ: {settings.ai_provider} / 類似度チェック: {settings.similarity_backend}")

    if not _configured_ai_api_key():
        st.warning(
            f".envに{'OPENAI_API_KEY' if settings.ai_provider == 'openai' else 'ANTHROPIC_API_KEY'}"
            "が設定されていません。生成は実行できません。"
        )
    elif not eligible:
        st.info("生成対象の投稿はありません（viral_scoreの閾値以上かつ未生成の投稿が0件です）。")
    else:
        if len(eligible) == 1:
            limit = 1
            st.caption("生成対象の投稿は1件です。")
        else:
            limit = st.slider("生成する件数", min_value=1, max_value=len(eligible), value=min(5, len(eligible)))

        if st.button("投稿を生成する", type="primary"):
            try:
                client = get_ai_client(settings, logger=logger)
                similarity_checker = get_similarity_checker(settings, logger=logger)
            except ThreadsToolError as exc:
                st.error(f"クライアントの初期化に失敗しました: {exc}")
                client = None

            if client is not None:
                ai_model = settings.openai_model if settings.ai_provider == "openai" else settings.anthropic_model
                with st.spinner("生成中...（類似度・安全性チェックのため投稿ごとに複数回AIを呼び出します）"):
                    with session_scope(session_factory) as session:
                        target_posts = eligible[:limit]
                        analysis_repo = AnalysisRepository(session)
                        items = [(p, analysis_repo.get_by_post_id(p.id)) for p in target_posts]
                        results = run_generation_batch(
                            client, similarity_checker, session, items, settings, settings.ai_provider, ai_model, logger
                        )
                client.close()
                similarity_checker.close()

                candidate_count = sum(1 for r in results if r.status == "candidate")
                review_count = sum(1 for r in results if r.status == "manual_review")
                error_count = sum(1 for r in results if not r.ok)
                st.success(
                    f"生成完了: candidate={candidate_count} manual_review={review_count} error={error_count}"
                    "（画面上部の件数は次の操作で更新されます）"
                )
                for r in results:
                    if not r.ok:
                        st.error(f"source_post_id={r.source_post_id}: {r.error}")
                    elif r.status == "manual_review":
                        st.warning(f"source_post_id={r.source_post_id}: manual_review行き（{r.attempts}回試行）")

    st.divider()
    st.subheader("生成結果 / レビュー")
    status_filter = st.selectbox(
        "状態で絞り込み", ["すべて", "candidate", "manual_review", "approved", "rejected"]
    )
    with session_scope(session_factory) as session:
        rows = GeneratedPostRepository(session).list_by_status(
            None if status_filter == "すべて" else status_filter
        )
        source_posts = {p.id: p for p in PostRepository(session).list_posts(PostFilter(), limit=10000)}
        analyses = {row.source_post_id: AnalysisRepository(session).get_by_post_id(row.source_post_id) for row in rows}

    st.caption(f"{len(rows)} 件")

    STATUS_LABELS = {
        "candidate": "候補",
        "manual_review": "要確認",
        "approved": "承認済み",
        "rejected": "却下済み",
    }

    for row in rows:
        source = source_posts.get(row.source_post_id)
        analysis = analyses.get(row.source_post_id)
        score_label = f" {analysis.viral_score}点" if analysis else ""
        title = f"[{STATUS_LABELS.get(row.status, row.status)}]{score_label} {source.keyword if source else '?'} (試行{row.attempt_count}回)"

        with st.expander(title):
            if source:
                st.markdown("**元投稿**")
                st.write(source.text)
                if source.permalink:
                    st.markdown(f"[元投稿を開く]({source.permalink})")
            if analysis:
                st.markdown("**AI分析**")
                st.json(
                    {
                        "theme": analysis.theme,
                        "hook": analysis.hook,
                        "structure": analysis.structure,
                        "emotion": analysis.emotion,
                        "cta": analysis.cta,
                        "target_reader": analysis.target_reader,
                        "viral_score": analysis.viral_score,
                    }
                )
            st.markdown("**生成された投稿案**")
            st.write(row.generated_text)
            st.markdown("**類似度・安全性チェック結果**")
            st.json(
                {
                    "semantic_similarity": row.semantic_similarity,
                    "string_similarity": row.string_similarity,
                    "similarity_backend": row.similarity_backend,
                    "duplicate_similarity": row.duplicate_similarity,
                    "is_safe": row.is_safe,
                    "safety_violations": json.loads(row.safety_violations) if row.safety_violations else [],
                    "safety_reason": row.safety_reason,
                    "rejection_reason": row.rejection_reason,
                }
            )

            b1, b2, b3 = st.columns(3)
            if row.status in ("candidate", "manual_review"):
                if b1.button("承認", key=f"approve_{row.id}", type="primary"):
                    with session_scope(session_factory) as session:
                        GeneratedPostRepository(session).set_status(row.id, "approved")
                    st.rerun()
                if b2.button("却下", key=f"reject_{row.id}"):
                    with session_scope(session_factory) as session:
                        GeneratedPostRepository(session).set_status(row.id, "rejected")
                    st.rerun()
            else:
                b1.caption(f"レビュー済み: {row.reviewed_at}")

            if b3.button("再生成", key=f"regenerate_{row.id}"):
                if source is None or analysis is None:
                    st.error("元投稿またはAI分析結果が見つからないため再生成できません。")
                else:
                    try:
                        client = get_ai_client(settings, logger=logger)
                        similarity_checker = get_similarity_checker(settings, logger=logger)
                    except ThreadsToolError as exc:
                        st.error(f"クライアントの初期化に失敗しました: {exc}")
                    else:
                        ai_model = (
                            settings.openai_model if settings.ai_provider == "openai" else settings.anthropic_model
                        )
                        with st.spinner("再生成中..."):
                            with session_scope(session_factory) as session:
                                result = generate_post(
                                    client,
                                    similarity_checker,
                                    session,
                                    source,
                                    analysis,
                                    settings,
                                    settings.ai_provider,
                                    ai_model,
                                    logger=logger,
                                )
                        client.close()
                        similarity_checker.close()
                        if result.ok:
                            st.success(f"再生成完了: status={result.status}（{result.attempts}回試行）")
                            st.rerun()
                        else:
                            st.error(f"再生成に失敗しました: {result.error}")


def render_publishing() -> None:
    st.header("Threads投稿")
    st.caption(
        "承認済みの投稿案のみ、ボタンを押したときだけTheadsへ投稿されます。自動では投稿されません。"
    )

    if settings.auto_post:
        st.warning(
            "AUTO_POST=true が設定されています。この設定の場合、`scripts/run_publish.py` は承認済みの"
            "投稿すべてを人の確認なしで投稿できます。この画面のボタンは常に手動クリックが必要です。"
        )

    with session_scope(session_factory) as session:
        status_counts = GeneratedPostRepository(session).count_by_status()
        publishable = GeneratedPostRepository(session).list_publishable(limit=200)
        posted = GeneratedPostRepository(session).list_by_status("posted", limit=200)
        source_posts = {p.id: p for p in PostRepository(session).list_posts(PostFilter(), limit=10000)}

    col1, col2 = st.columns(2)
    col1.metric("投稿待ち（承認済み・未投稿）", len(publishable))
    col2.metric("投稿済み", status_counts.get("posted", 0))

    if not settings.threads_access_token:
        st.warning(".envにTHREADS_ACCESS_TOKENが設定されていません。投稿できません。")
        return
    if not settings.threads_user_id:
        st.warning(".envにTHREADS_USER_IDが設定されていません。投稿できません。")
        return

    st.divider()
    st.subheader("投稿待ち")
    if not publishable:
        st.info("投稿待ちの承認済み投稿はありません。")
    for row in publishable:
        source = source_posts.get(row.source_post_id)
        preview = row.generated_text[:40] + ("…" if len(row.generated_text) > 40 else "")
        with st.expander(f"{source.keyword if source else '?'} / {preview}"):
            st.write(row.generated_text)
            if source:
                st.caption(f"元投稿キーワード: {source.keyword}")

            if st.button("Threadsに投稿する", key=f"publish_{row.id}", type="primary"):
                try:
                    client = ThreadsClient(
                        access_token=settings.threads_access_token,
                        base_url=settings.threads_api_base_url,
                        timeout_seconds=settings.threads_api_timeout_seconds,
                        max_retries=settings.threads_api_max_retries,
                        backoff_base_seconds=settings.threads_api_backoff_base_seconds,
                        logger=logger,
                    )
                except ThreadsToolError as exc:
                    st.error(f"Threads APIクライアントの初期化に失敗しました: {exc}")
                else:
                    wait_s = settings.threads_publish_wait_seconds
                    with st.spinner(f"投稿中...（コンテナ作成後、約{wait_s:.0f}秒待機してから公開します）"):
                        with session_scope(session_factory) as session:
                            result = publish_generated_post(
                                client,
                                session,
                                row,
                                settings.threads_user_id,
                                wait_s,
                                logger=logger,
                            )
                    client.close()

                    if result.ok:
                        st.success(f"投稿完了: threads_post_id={result.threads_post_id}")
                        if result.permalink:
                            st.markdown(f"[投稿を開く]({result.permalink})")
                        st.rerun()
                    else:
                        st.error(f"投稿に失敗しました: {result.error}")

    st.divider()
    st.subheader("投稿済み")
    st.caption(f"{len(posted)} 件")
    for row in posted:
        source = source_posts.get(row.source_post_id)
        title = f"{source.keyword if source else '?'} (投稿日時: {row.published_at})"
        with st.expander(title):
            st.write(row.generated_text)
            if row.published_permalink:
                st.markdown(f"[投稿を開く]({row.published_permalink})")
            st.caption(f"threads_post_id: {row.threads_post_id}")


PAGES = {
    "Dashboard": render_dashboard,
    "Posts": render_posts,
    "検索実行 / キーワード管理": render_search_and_keywords,
    "AI分析": render_analysis,
    "投稿生成": render_generation,
    "Threads投稿": render_publishing,
}

page = st.sidebar.radio("ページ", list(PAGES.keys()))
st.sidebar.caption(f"DB: {settings.database_path}")

try:
    PAGES[page]()
except Exception as exc:  # last-resort guard so a page error doesn't take down the whole app
    logger.error("UI予期せぬエラー: page=%s error=%s", page, exc)
    st.error(f"予期しないエラーが発生しました: {exc}")
