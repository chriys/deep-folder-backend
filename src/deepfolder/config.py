"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/deepfolder"
    secret_key: str = "change-me-in-production"
    allowed_emails: list[str] = []
    debug: bool = False

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    voyage_api_key: str = ""
    embedding_model: str = "voyage-4"
    embedding_dimension: int = 1024
    reranker_model: str = "voyage-3-rerank"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    spend_cap_usd: float = 10.0

    sentry_dsn: str | None = Field(default=None)


# Pinned price table: cost USD per 1M tokens.
# NOTE: Update these prices when models are re-pinned.
MODEL_PRICES: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input_per_1m": 2.00, "output_per_1m": 8.00},
    "voyage-4": {"input_per_1m": 0.10, "output_per_1m": 0.00},
    "voyage-3-rerank": {"input_per_1m": 1.00, "output_per_1m": 0.00},
}

settings = Settings()
