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


settings = Settings()
