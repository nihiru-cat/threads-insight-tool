"""Application configuration, loaded from environment variables / .env.

Secrets (THREADS_ACCESS_TOKEN) live only in process memory once loaded here.
Never log `settings.threads_access_token` directly — use
`app.logging_config.mask_secret` if it ever needs to appear in a message.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Threads API ---
    threads_access_token: str = Field(default="", description="Threads long-lived user access token")
    threads_api_base_url: str = Field(default="https://graph.threads.net/v1.0")
    threads_api_timeout_seconds: float = Field(default=10.0)
    threads_api_max_retries: int = Field(default=3)
    threads_api_backoff_base_seconds: float = Field(default=1.0)
    # Default page size per keyword_search call (API max is 100).
    threads_api_search_limit: int = Field(default=25, ge=1, le=100)

    # --- AI analysis (Phase 2) ---
    # "openai" or "anthropic" — selects which client app.services.ai.factory builds.
    ai_provider: str = Field(default="anthropic")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-5")
    ai_timeout_seconds: float = Field(default=30.0)
    # Retries for transient errors (timeout/429/5xx) talking to the AI provider.
    ai_max_retries: int = Field(default=3)
    ai_backoff_base_seconds: float = Field(default=1.0)
    # Retries when the model's response isn't valid JSON / doesn't match the schema
    # (a different failure mode than a network error — no backoff, just re-ask).
    ai_max_parse_retries: int = Field(default=2)

    # --- Original post generation (Phase 3) ---
    # Only posts with an AI analysis viral_score >= this are eligible for generation.
    generation_min_viral_score: int = Field(default=70, ge=0, le=100)
    # After the first generation attempt, how many additional regeneration attempts
    # to make if a candidate is rejected (similarity or safety) before giving up and
    # marking the post `manual_review`. Total attempts made = 1 + this value.
    generation_max_regenerations: int = Field(default=3, ge=0)

    # Similarity backend: "auto" uses OpenAI embeddings if OPENAI_API_KEY is set
    # (Anthropic has no embeddings endpoint), otherwise falls back to a string-based
    # similarity ratio (difflib). "string" forces the string-based backend even if an
    # OpenAI key is available. "openai_embedding" forces embeddings (errors if no key).
    similarity_backend: str = Field(default="auto")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    # A candidate is rejected as too similar to its source post at or above this score.
    semantic_similarity_reject_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    # A candidate is rejected as a near-duplicate of another already-generated
    # candidate (across all source posts) at or above this score.
    duplicate_similarity_reject_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    # How many of the most recent generated candidates to compare a new draft
    # against for the mass-duplicate check.
    duplicate_check_pool_size: int = Field(default=50, ge=0)

    # --- Threads publishing (Phase 5) ---
    # The numeric Threads user id to publish as (distinct from the access
    # token) — required for both the container-create and publish endpoints.
    threads_user_id: str = Field(default="")
    # Recommended wait between creating a media container and publishing it
    # (documented recommendation, not a value we invented).
    threads_publish_wait_seconds: float = Field(default=30.0, ge=0.0)
    # Never auto-post by default. False: publishing an approved candidate
    # always requires an explicit click in the Streamlit UI. True: in
    # addition to the UI, scripts/run_publish.py is allowed to publish every
    # approved-and-unposted candidate unattended (e.g. from cron) — never
    # flip this on without understanding what that means for your account.
    auto_post: bool = Field(default=False)

    # --- Storage ---
    database_path: Path = Field(default=PROJECT_ROOT / "data" / "threads_insight.db")

    # --- Logging ---
    log_dir: Path = Field(default=PROJECT_ROOT / "logs")
    log_level: str = Field(default="INFO")

    @property
    def database_url(self) -> str:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
