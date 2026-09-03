# Threads Insight Tool

Threads（Meta）の公開投稿を `keyword_search` APIで調査し、SQLiteに保存してStreamlitで一覧表示するツールです。

**現在の実装状況: Phase 1〜5（検索・保存・AI分析・オリジナル投稿生成・承認レビュー・Threads投稿）まですべて完成しています。**

## アーキテクチャ

```
app/
  config/          # .env読み込み・アプリ設定 (pydantic-settings)
  models/          # SQLAlchemy ORMモデル (Post, Keyword, PostAnalysis, GeneratedPost)
  schemas/         # 外部入力の検証用 Pydanticスキーマ
    post.py          # Threads APIレスポンス検証
    analysis.py       # AI分析結果の厳密なJSONスキーマ (extra="forbid")
    generation.py     # AI生成投稿案の厳密なJSONスキーマ
    safety.py         # AI安全性チェック結果の厳密なJSONスキーマ
  repositories/    # DBアクセス層 (重複排除・検索フィルタ・集計)
  services/
    threads_client.py   # Threads API HTTPクライアント (keyword_search + 投稿publish、リトライ/バックオフ)
    search_service.py   # 検索→保存のオーケストレーション、エラーの局所化
    analysis_service.py # プロンプト構築→AI呼び出し→JSON検証→保存のオーケストレーション
    safety_service.py   # 生成投稿案のAI安全性チェック
    generation_service.py # 抽象化された型のみから投稿案を生成→類似度/安全性チェック→再生成→保存
    publishing_service.py # 承認済み投稿案をThreadsへpublish→DBに投稿結果を記録（二重投稿防止つき）
    ai/
      base.py            # プロバイダ非依存の AIClient 抽象クラス (共通リトライロジック)
      json_utils.py      # AI応答のJSON抽出+スキーマ検証+再試行の共通ロジック
      openai_client.py   # OpenAI実装
      anthropic_client.py # Anthropic実装
      factory.py         # AI_PROVIDER設定から実装クラスを選択
    similarity/
      base.py                     # プロバイダ非依存の SimilarityChecker 抽象クラス
      string_similarity.py        # difflibベースの文字列類似度（常時利用可能）
      openai_embedding_similarity.py # OpenAI embeddingsベースの意味的類似度
      factory.py                  # SIMILARITY_BACKEND設定から実装クラスを選択
  ui/
    streamlit_app.py    # Streamlit管理画面 (Dashboard / Posts / 検索実行 / AI分析 / 投稿生成 / Threads投稿)
  db.py            # SQLAlchemy engine/sessionセットアップ
  logging_config.py  # logs/app.log 出力、シークレットマスキング
  exceptions.py    # アプリ内カスタム例外
scripts/
  init_db.py       # DB初期化＋デフォルトキーワード投入
  run_search.py    # Streamlitを使わずCLIから検索を実行するツール
  run_analysis.py  # StreamlitなしでCLIからAI分析を実行するツール
  run_generation.py # StreamlitなしでCLIから投稿生成を実行するツール
  run_publish.py   # 承認済み投稿を無人でThreadsへ投稿するツール（AUTO_POST=trueの場合のみ実行可）
tests/             # pytest（HTTP/AI呼び出しはモック、DBは一時SQLite）
data/              # SQLiteファイルの保存先（.gitignore対象）
logs/              # app.logの保存先（.gitignore対象）
```

設計方針:
- **検索キーワードはコード非依存**: `keywords` テーブルに保存し、Streamlit画面から追加/削除できます。初回起動時のみデフォルト7キーワード（占い/スピリチュアル/引き寄せ/復縁/ツインレイ/運気/開運）を自動投入します。
- **取得できないデータは捏造しない**: Threads APIの `keyword_search` は他人の投稿の `like_count` 等のエンゲージメント指標を公式には返しません。本ツールはドキュメントに存在するフィールドのみ (`id, text, timestamp, permalink, username, media_type, has_replies, is_quote_post, is_reply`) を要求・保存します。
- **viral_scoreはエンゲージメント指標なしで推定**: 上記の制約を前提に、AI分析（`app/schemas/analysis.py` / `app/services/analysis_service.py`）はフックの強さ・テーマ適合度・感情訴求・コメント誘導力・構成の再利用しやすさ・新規投稿への展開しやすさ、の6観点から0-100点を推定します。いいね数などが取得可能になった場合でも、実測値と推定値を混同しないよう別カラムで扱ってください。
- **AIプロバイダは抽象化**: `AnalysisService` / `GenerationService` は `app.services.ai.base.AIClient` インターフェースにのみ依存し、OpenAI/Anthropicの具体的なSDKを知りません。プロバイダの切り替えは `.env` の `AI_PROVIDER` を変更するだけで、コード変更は不要です。
- **コピー防止は構造的**: 投稿生成のプロンプト（`app/services/generation_service.py`）は元投稿のAI分析結果（theme/hook/structure/cta/target_reader という抽象化された型情報）のみから組み立てられ、**元投稿の本文そのものはAIに一切渡されません**。文章をコピーしたり言い換えたりすることは、そもそも元の文章を見せていないため構造的に不可能です。類似度チェックは、それでも学習データからの想起等で似てしまった場合の第二の防御線です。
- **類似度チェックも抽象化**: `app.services.similarity.base.SimilarityChecker` インターフェースの下に、常時利用可能な文字列類似度（difflib）と、OpenAI embeddingsによる意味的類似度の2実装があります。Anthropicはembeddings APIを提供していないため、`SIMILARITY_BACKEND=auto`（デフォルト）はOPENAI_API_KEYがあればembeddingsを、なければ文字列類似度にフォールバックします。
- **エラーはジョブ単位で局所化**: 1つの(キーワード, search_type)・1投稿の分析・1投稿の生成・1投稿のpublishの失敗が他のジョブやアプリ全体を落とさないよう、各serviceはAPI/DB/JSON検証エラーを結果オブジェクトに格納して返します。AI応答がJSONスキーマに一致しない場合は`AI_MAX_PARSE_RETRIES`回まで再度AIに問い合わせ、それでも失敗すれば保存されません（分析は該当投稿をスキップ、生成はエラーとして扱われます）。
- **投稿は承認済みのみ・自動投稿はデフォルト無効**: `app/services/publishing_service.py`は`status="approved"`の候補しかThreadsへ投稿しません（`AUTO_POST`の値に関わらず不変のルールです）。`AUTO_POST=false`（初期値）ではStreamlit画面の手動クリックのみで投稿でき、`scripts/run_publish.py`は実行自体を拒否します。二重投稿防止は「投稿成功後は`status`が`approved`から`posted`へ遷移し、以後`list_publishable()`に出てこなくなる」という状態遷移そのもので保証しています（別フラグの整合性管理に依存しません）。投稿は成功したがDB書き込みだけ失敗した場合も、エラーメッセージに実際の`threads_post_id`を含めて表示し、サイレントに握りつぶさないようにしています。

## 必要環境

- Python 3.12以上
- macOS / Linux / Windows（WSL推奨）
- Threads（Meta for Developers）アプリの作成、および `threads_basic` / `threads_keyword_search` 権限の承認（Phase 5の投稿機能を使う場合は `threads_content_publish` 権限も必要）

> **このマシンのメモ**: セットアップ時点でシステムの `python3` は 3.9 系だったため、動作確認用に
> Python 3.12.6（standalone build）を `~/.local/opt/python3.12-standalone` に配置し、`.venv` を
> そのPythonで作成済みです。既に `.venv` があるので、以下の手順1〜2は多くの場合スキップして
> `source .venv/bin/activate` だけで動作します。別環境に持ち出す場合や `.venv` を作り直す場合は、
> `~/.local/opt/python3.12-standalone/bin/python3.12 -m venv .venv` のようにPython 3.12以上の
> インタプリタを指定してください。

## セットアップ

### 1. Pythonセットアップ・仮想環境

```bash
python3 --version   # 3.12以上であることを確認
python3 -m venv .venv
source .venv/bin/activate   # Windowsは .venv\Scripts\activate
```

### 2. 依存パッケージのインストール

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Meta Developers / Threads API設定

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作成します。
2. アプリに Threads API プロダクトを追加します。
3. `threads_basic` と `threads_keyword_search` の権限をリクエストします（Phase 5の投稿機能を使う場合は `threads_content_publish` も）。
   - `threads_keyword_search` は承認されるまで自分自身の投稿しか検索できません。他ユーザーの公開投稿を検索するには Meta のアプリレビュー（App Review）の承認が必要です。
4. 承認後、長期アクセストークン（long-lived user access token）を発行します。
5. トークンには有効期限があります。期限切れ時は再発行し `.env` を更新してください。
6. （Phase 5用）投稿先の数値のThreadsユーザーID（アクセストークンとは別物）を確認し、`.env`の`THREADS_USER_ID`に設定します。

参考: https://developers.facebook.com/docs/threads/keyword-search/ 、 https://developers.facebook.com/docs/threads/posts

### 4. AI APIキーの取得（Phase 2: AI分析用）

`AI_PROVIDER` で指定した方のAPIキーだけを用意すれば動作します（両方は不要）。

- **Anthropic（デフォルト）**: https://console.anthropic.com/ でAPIキーを発行してください。
- **OpenAI**: https://platform.openai.com/api-keys でAPIキーを発行してください。

### 5. .env設定

```bash
cp .env.example .env
```

`.env` を開き、以下を設定してください。
- `THREADS_ACCESS_TOKEN`: 手順3で取得したThreadsアクセストークン（Phase 1の検索実行に必要）
- `AI_PROVIDER`: `anthropic` または `openai`
- `ANTHROPIC_API_KEY` または `OPENAI_API_KEY`: 手順4で取得したAPIキー（選んだ方のみでOK）
- （Phase 5用）`THREADS_USER_ID`: 手順3-6で確認した数値のThreadsユーザーID
- （Phase 5用）`AUTO_POST`: 初期値`false`のままにしておくことを推奨します。意味は下記「Threads投稿」を参照してください。

`.env` は `.gitignore` 済みです。**絶対にリポジトリへコミットしないでください。**

### 6. DB初期化

```bash
python scripts/init_db.py
```

`data/threads_insight.db` が作成され、デフォルトキーワードが投入されます（Streamlit初回起動時にも自動実行されます）。

### 7. Streamlit起動

```bash
streamlit run app/ui/streamlit_app.py
```

ブラウザで `http://localhost:8501` を開くと、以下の6画面が使えます。

- **Dashboard**: DB保存投稿数、本日取得件数、キーワード別/search_type別件数
- **Posts**: 保存済み投稿の一覧（キーワード・search_type・日付で絞り込み可能）
- **検索実行 / キーワード管理**: キーワードの追加・削除・有効/無効切り替え、Threads APIへの検索実行
- **AI分析**: 未分析投稿数の確認、AI分析の実行、分析結果（theme/hook/structure/emotion/cta/target_reader/viral_score/reason）の閲覧・viral_scoreによる絞り込み
- **投稿生成**: viral_scoreが閾値（デフォルト70）以上で未生成の投稿から、オリジナル投稿案を生成。生成結果一覧で元投稿・AI分析（viral_score含む）・生成案・類似度・安全性チェック結果・statusを確認でき、`candidate`/`manual_review`の各案を**承認**・**却下**でき、どの状態からでも**再生成**（新しい生成案を追加作成）できます
- **Threads投稿**: 承認済み（`approved`）で未投稿の投稿案一覧を表示し、1件ずつボタンを押してThreadsへ実際に投稿できます。投稿するとステータスが`posted`になり、二度と同じ候補が投稿対象に出てこなくなります（二重投稿防止）。投稿済み一覧では実際のpermalinkを確認できます

### 8. CLIから実行する場合（任意）

```bash
# Threads検索
python scripts/run_search.py --all-active-keywords --search-type TOP RECENT

# AI分析（未分析の投稿を最大10件）
python scripts/run_analysis.py --limit 10

# 投稿生成（viral_score>=閾値の未生成投稿を最大5件）
python scripts/run_generation.py --limit 5

# Threads投稿（承認済み・未投稿の候補を無人で投稿。.envで AUTO_POST=true の場合のみ実行可）
python scripts/run_publish.py --limit 10
```

### 9. テスト実行

```bash
pytest
```

## Threads投稿とAUTO_POSTについて（Phase 5）

このツールは、最初から完全自動で投稿することはありません。承認済み（`approved`）の投稿案だけが投稿対象になり、それは`AUTO_POST`の値に関わらず常に守られるルールです。

- **`AUTO_POST=false`（初期値・推奨）**: Streamlitの「Threads投稿」画面から、1件ずつ「Threadsに投稿する」ボタンを押した場合のみ投稿されます。`scripts/run_publish.py`はこの設定では**実行自体を拒否**します（cron等で無人実行してしまう事故を防ぐため）。
- **`AUTO_POST=true`**: 上記の手動投稿に加えて、`scripts/run_publish.py`が承認済み・未投稿のすべての候補を人の確認なしに投稿できるようになります。cron等で定期実行する場合のみ有効にしてください。

投稿フローの実際の処理（`app/services/threads_client.py` / `app/services/publishing_service.py`）:
1. メディアコンテナを作成 (`POST /{threads-user-id}/threads`, media_type=TEXT)
2. Meta推奨の約30秒（`THREADS_PUBLISH_WAIT_SECONDS`で変更可）待機
3. コンテナを公開 (`POST /{threads-user-id}/threads_publish`)
4. permalinkを取得 (`GET /{media-id}?fields=permalink`) — ここで失敗しても投稿自体は成功しているため、エラーとして再投稿はされません（permalinkは`None`のまま保存され、後で確認できます）
5. DBに`threads_post_id` / `published_at` / `published_permalink`を保存し、statusを`approved`→`posted`に変更

**二重投稿防止**は、この最後のstatus遷移そのもので実現しています。`posted`になった候補は「投稿待ち」一覧（`list_publishable()`、内部的には`status="approved"`のみを返します）に二度と出てきません。万が一「投稿には成功したがDB保存だけ失敗した」場合は、エラーメッセージに実際の`threads_post_id`を表示し、手動でのDB修正を促します（サイレントに失敗として扱い再投稿を許してしまうことはありません）。

## よくあるエラー

| 症状 | 原因・対処 |
|---|---|
| `ThreadsAuthError: THREADS_ACCESS_TOKEN is not set` | `.env` にトークンが未設定。`.env.example` をコピーして設定してください。 |
| 検索実行時に `Auth error (401/403)` | トークンが無効/期限切れ、または `threads_keyword_search` 権限が未承認。Meta for Developersでトークンと権限を確認してください。 |
| 検索実行時に `Rate limited (429)` | Threads APIのレート制限（24時間あたり最大2,200クエリ）に達しています。時間を置いて再実行してください。 |
| `ModuleNotFoundError: No module named 'app'` | 仮想環境の有効化を忘れているか、プロジェクトルート以外から実行しています。`cd` してから `source .venv/bin/activate` してください。 |
| Streamlitで日本語キーワードが検索できない | Threads APIの `q` パラメータはURLエンコードされたUTF-8文字列をサポートしています。トークンの権限（`threads_keyword_search`）を確認してください。 |
| `sqlite3.OperationalError: database is locked` | 複数プロセスから同時に同じSQLiteファイルへ書き込んだ場合に発生し得ます。Streamlitと`run_search.py`/`run_analysis.py`を同時実行しないでください。 |
| `AIAuthError: ANTHROPIC_API_KEY is not set` / `OPENAI_API_KEY is not set` | `.env` の `AI_PROVIDER` で選んだ方のAPIキーが未設定。`.env.example` を参照して設定してください。 |
| AI分析実行時に `Anthropic auth error: ... invalid x-api-key` 等 | APIキーが無効・期限切れ、または該当プロバイダのアカウントに残高/権限がありません。コンソールでキーを確認してください。 |
| AI分析実行時に `AI応答が期待するJSONスキーマに一致しませんでした` | AIモデルの応答がJSONとして解析できないか、フィールドが不足/型が不正でした。`AI_MAX_PARSE_RETRIES`回まで自動再試行した上での失敗です。当該投稿はDBに保存されず、再度「未分析の投稿を分析する」で再試行できます。 |
| 投稿生成が全件 `manual_review` になる | `SEMANTIC_SIMILARITY_REJECT_THRESHOLD` / `DUPLICATE_SIMILARITY_REJECT_THRESHOLD` が厳しすぎるか、`GENERATION_MAX_REGENERATIONS`が少なすぎる可能性があります。生成結果の`rejection_reason`で具体的な却下理由を確認してください。 |
| 投稿生成が遅い / AI呼び出し回数が多い | 1回の生成試行につき「投稿案生成」「安全性チェック」の2回AIを呼び出し、`SIMILARITY_BACKEND=openai_embedding`（またはauto+OPENAI_API_KEY設定時）はさらにembeddings呼び出しが加わります。`GENERATION_MAX_REGENERATIONS`を減らすと呼び出し回数の上限を抑えられます。 |
| `SimilarityBackendError: Unknown SIMILARITY_BACKEND=...` | `.env`の`SIMILARITY_BACKEND`が`auto`/`string`/`openai_embedding`のいずれでもありません。スペルを確認してください。 |
| `run_publish.py`が`AUTO_POST=false のため、このスクリプトは実行できません`と表示して終了する | 意図通りの動作です（初期設定での安全装置）。人が確認しながら投稿する場合はStreamlitの「Threads投稿」画面を使うか、無人実行を意図している場合のみ`.env`で`AUTO_POST=true`にしてください。 |
| Threads投稿時に `Bad request (400) ... Invalid OAuth access token` | アクセストークンが無効、または`THREADS_USER_ID`が誤っています（アクセストークンとThreadsユーザーIDは別物です）。 |
| Threads投稿時に `response missing 'id'` (`ThreadsInvalidResponseError`) | Threads API側のレスポンス形式が変わった可能性があります。`app/services/threads_client.py`の`create_container`/`publish_container`が期待するレスポンス形式を、公式ドキュメントで確認してください。 |
| 投稿が「投稿待ち」に残ったまま消えない | 投稿処理でエラーが出ている可能性があります。エラーメッセージ（画面またはlogs/app.log）を確認してください。エラーが出ずに投稿だけ実際には成功しているのにDB上`approved`のままという状態は、DB保存自体の失敗時のみ発生し、その場合はエラーメッセージに実際の`threads_post_id`が表示されます。 |
| `ModuleNotFoundError: No module named 'app'`（scriptsを直接実行時） | 各`scripts/*.py`はファイル自身の場所からプロジェクトルートを`sys.path`に追加するようになっているため、通常は`cd`さえしていればどこから実行しても発生しません。発生する場合は`scripts/`配下のファイルが壊れていないか確認してください。 |

## Phase 1 完成条件チェックリスト

- [x] `.env` からThreadsアクセストークンを読み込める（`app/config/settings.py`）
- [x] Threads APIへ接続できる（`app/services/threads_client.py`）
- [x] 少なくとも1つのキーワードを検索できる
- [x] 取得した投稿をSQLiteへ保存できる（`app/repositories/post_repository.py`）
- [x] 同一`thread_id`を二重保存しない（UNIQUE制約 + アプリ側dedup）
- [x] Streamlitで保存投稿を一覧表示できる
- [x] エラー時にアプリ全体がクラッシュしない（ジョブ単位でエラーを捕捉）
- [x] `pytest` が通る
- [x] READMEに起動方法を記載

## Phase 2 完成条件チェックリスト

- [x] 投稿ごとにtheme/hook/structure/emotion/cta/target_reader/viral_score/reasonをJSONで生成（`app/services/analysis_service.py`）
- [x] Pydanticで厳密に検証（`app/schemas/analysis.py`、`extra="forbid"` + 空文字禁止 + viral_scoreは0-100の整数のみ）
- [x] viral_scoreはいいね数等に依存せず、フックの強さ等6観点からAIが推定（プロンプトに明記）
- [x] AI APIはOpenAI/Anthropicのどちらにも差し替え可能（`app/services/ai/` の抽象化、`.env`の`AI_PROVIDER`で切替）
- [x] AI応答がスキーマ不一致の場合は`AI_MAX_PARSE_RETRIES`回まで再試行、それでも失敗すれば保存せずエラーとして扱う
- [x] StreamlitのAI分析画面から実行・結果閲覧・viral_scoreでの絞り込みができる
- [x] `pytest` が通る（うち一部は実際の`openai`/`anthropic` SDK例外クラスを用いた例外マッピングのテスト）
- [x] 実際のAnthropic APIに対する接続確認（無効なキーで401を再現し、`AIAuthError`へのマッピングとエラーメッセージ表示、DB未保存を確認済み）

## Phase 3 完成条件チェックリスト

- [x] viral_score>=70（`GENERATION_MIN_VIRAL_SCORE`で変更可）の投稿からオリジナル投稿案を生成
- [x] 元投稿の文章をコピーしない: 生成プロンプトに元投稿の本文を一切含めない構造（`app/services/generation_service.py`のbuild_user_prompt）で、コピー・言い換え・言い回しの流用を構造的に不可能にしている
- [x] 参考にするのは抽象化された構造・テーマカテゴリ・フックの型・CTAの型のみ（AI分析結果の該当フィールドのみをプロンプトに使用）
- [x] 類似度チェック: 文字列一致率（difflib）に加え、意味的類似度（OpenAI embeddings、`SIMILARITY_BACKEND`で切替可能な抽象化された仕組み）を実装
- [x] 閾値はconfigから変更可能（`SEMANTIC_SIMILARITY_REJECT_THRESHOLD`初期値0.80、`DUPLICATE_SIMILARITY_REJECT_THRESHOLD`初期値0.80）
- [x] 閾値以上の類似度の場合は不採用とし自動再生成、最大再生成回数は`GENERATION_MAX_REGENERATIONS`（初期値3）で変更可能、失敗時は`manual_review`状態で保存
- [x] コンテンツ安全チェック: 個人への攻撃・医療/法律/金融の断定・誇大表現・不安煽り表現をAIで判定し、問題があれば不採用（`app/services/safety_service.py`）。同一内容の大量生成は生成済み投稿プールとの類似度比較で検出
- [x] StreamlitのAI分析画面と同様、投稿生成画面から実行・結果閲覧（元投稿/生成案/類似度/安全性チェック結果/status）ができる
- [x] `pytest` が通る（106 tests passed）
- [x] 実際のAnthropic APIに対する接続確認（無効なキーで、投稿生成の2投稿分の生成呼び出しがそれぞれ独立して401→`AIAuthError`にマッピングされること、DB未保存であることを確認済み）

## Phase 4 完成条件チェックリスト

- [x] Streamlitに元投稿・AI分析（viral_score含む）・生成投稿案・類似度/安全性チェック結果を集約表示（`app/ui/streamlit_app.py`のrender_generation内、生成結果/レビューセクション）
- [x] 承認ボタン: `candidate`/`manual_review`の案を`approved`にし、`reviewed_at`を記録（`app/repositories/generated_post_repository.py`のset_status）
- [x] 却下ボタン: 同様に`rejected`にできる
- [x] 再生成ボタン: 任意のstatusの案に対し、同じ元投稿・AI分析から新しい生成ジョブ（`generation_service.generate_post`）を再実行し、新しい行として追加保存（既存の案は変更・削除されない＝履歴が残る）
- [x] manual_review状態の投稿は一覧・絞り込みで確認でき、承認/却下/再生成のいずれかの人間判断を待てる
- [x] `pytest` が通る（110 tests passed）
- [x] 実際のUI操作で承認/却下/再生成を検証（ブラウザ実機で、却下→ステータス反映、承認→ステータス反映、再生成→実際にAnthropic APIへ新規リクエストが飛び401エラーが握りつぶされずUIに表示されることを確認済み）

## Phase 5 完成条件チェックリスト

- [x] Threadsへの投稿機能を実装（`app/services/threads_client.py`のcreate_container/publish_container/get_permalink、`app/services/publishing_service.py`）。実装前に公式ドキュメントでコンテナ作成→約30秒待機→公開という2段階モデルであることを確認済み
- [x] 最初から完全自動投稿にしていない: `AUTO_POST`の初期値は`false`。この値に関わらずStreamlitからの投稿は常に人がボタンを押す必要があり、`scripts/run_publish.py`（無人実行用）は`AUTO_POST=true`のときのみ実行できる
- [x] 承認済み（`approved`）投稿のみThreadsへ投稿できる（`publishing_service.publish_generated_post`が非approvedを実行前に拒否し、`list_publishable()`もapprovedのみ返す）
- [x] 投稿成功後、Threads投稿ID・投稿時刻・permalink・statusを保存（`GeneratedPost.threads_post_id` / `published_at` / `published_permalink` / `status="posted"`、`GeneratedPostRepository.mark_published`）
- [x] 二重投稿防止を実装: 投稿済みの候補は`status`が`approved`から`posted`に遷移し、`list_publishable()`（投稿待ち一覧）に二度と出てこなくなる。permalink取得のみ失敗した場合も投稿自体は成功として扱い、再投稿を招く false failure を防止。DB保存自体が失敗した稀なケースも、実際の`threads_post_id`をエラーに含めて表示し沈黙させない
- [x] `pytest` が通る（128 tests passed）
- [x] 実際のThreads APIに対する接続確認: 無効なトークンでStreamlit画面・CLIスクリプトの両方から投稿を試行し、実際のOAuthエラー（code 190）を再現・正しくハンドリングされること、失敗時に候補が「投稿待ち」に残り続ける（＝再試行可能で、かつ誤って投稿済み扱いにならない）ことを確認済み

## 残っているTODO / 未確認事項

コード内にも `TODO(threads-api):` として記載していますが、まとめると以下の通りです。

- **ページング未対応**: `keyword_search` のページング仕様（`paging.cursors` の有無・形式）を一次情報で確認できていません。現状は `limit`（最大100件）の1ページのみ取得します。継続取得が必要な場合は公式ドキュメントで確認の上、`ThreadsClient.search` を拡張してください。
- **`keyword_search` のフィールド一覧はドキュメントの例示ベース**: Graph API系ノードのような網羅的なフィールドリファレンスが確認できなかったため、実際のレスポンスに未使用フィールドが含まれる可能性があります。新しいフィールドを使う場合は必ず公式ドキュメントで存在を確認してから追加してください。
- **AI分析・投稿生成・安全性チェックの成功パスは実APIコールで未検証**: このセットアップでは有効なAPIキーを用意していないため、認証エラーパス（401→各種AIエラーへのマッピング）は実際のAPI呼び出しで確認済みですが、正常系（有効なJSON応答の解析）はモックでのみ検証しています。有効なAPIキーを設定した上で一度実際に分析・生成を実行し、結果を確認してください。
- **AIモデルIDのデフォルト値は変更される可能性があります**: `.env.example` の `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `OPENAI_EMBEDDING_MODEL` のデフォルト値は本ドキュメント作成時点のものです。プロバイダ側でモデルが廃止/変更された場合は `.env` で更新してください。
- **意味的類似度のOpenAI embeddings実成功パスは未検証**: 同様に有効なOPENAI_API_KEYが無いため、`OpenAIEmbeddingSimilarityChecker`は例外マッピングのみ実APIで確認し、正常系（cosine類似度の妥当性）はモックでのみ検証しています。
- **安全性チェックの閾値・判定基準はプロンプトの記述に依存**: 「不安を過度に煽る」「誇大表現」などの境界線はAIの主観的判断によるため、実運用前に実際のキーで複数の投稿案を生成し、判定が意図通りか確認することを推奨します。
- **スキーママイグレーション未対応**: `GeneratedPost.reviewed_at`など、Phase 4で列を追加しました。`init_db()`は`create_all`のみでテーブル単位の作成しか行わず、既存テーブルへの列追加（ALTER）はしません。Phase 3以前に作成済みの`data/threads_insight.db`がある場合、Phase 4のコードでエラーになる可能性があります。開発中はDBファイルを削除して`python scripts/init_db.py`で作り直してください（Alembic等のマイグレーションツールは未導入です）。
- **承認取り消し(undo)は未実装**: 一度`approved`/`rejected`にした案を`candidate`に戻すUIはありません。判断を変える場合は「再生成」で新しい案を作成してください。
- **Threads投稿の成功パスは実APIコールで未検証**: 有効なThreadsアクセストークンを用意していないため、エラーパス（400 OAuthException等の各種`ThreadsAPIError`へのマッピング）は実際のAPI呼び出しで確認済みですが、正常系（コンテナ作成→約30秒待機→公開→permalink取得のフルフロー）はモックでのみ検証しています。実運用前に、有効なトークンで少なくとも1件テスト投稿し、実際にThreads上に反映されること・DBに正しい`threads_post_id`/`permalink`が保存されることを確認してください。
- **`threads_content_publish`権限とレート制限は未検証**: 投稿エンドポイントに必要な権限（`threads_content_publish`）やレート制限（1プロフィールあたり24時間で250投稿、ドキュメントで確認済みの値）は、実際にこの権限が付与されたアプリでの動作確認ができていません。
- **投稿の文字数制限は未検証**: ドキュメント上はテキスト投稿の上限は500文字（絵文字はUTF-8バイト数でカウント）とされていますが、本ツールはこの上限を事前チェックしていません。超過した場合の挙動（Threads API側のエラー）は未検証です。生成投稿案が長くなりすぎる場合は、超過時にAPIが返すエラーメッセージを確認の上、必要であれば`app/schemas/generation.py`にmax_length等のバリデーションを追加してください。
- **`GET /{media-id}?fields=permalink`のフィールド仕様はドキュメントの網羅的なリファレンスで確認できていません**: `keyword_search`と同じ`permalink`フィールド名を使っていますが、投稿publish後のメディアノードに対する公式の網羅的フィールドリファレンスは確認できませんでした。
