"""Application configuration via pydantic-settings."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sentry_dsn: str | None = Field(default=None)


settings = Settings()
