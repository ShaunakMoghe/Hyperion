from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILES = [
    str(path)
    for path in (
        PROJECT_ROOT / ".env.local",
        BACKEND_DIR / ".env.local",
    )
    if path.exists()
]


class Settings(BaseSettings):
    """Application configuration pulled from environment variables."""

    app_name: str = Field(default="Hyperion Backend", alias="APP_NAME")
    environment: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+psycopg://hyperion:hyperion@localhost:5432/hyperion",
        alias="DATABASE_URL",
    )
    app_secret_key: str = Field(default="dev-secret-change-me", alias="APP_SECRET_KEY")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    oidc_client_id: str = Field(default="replace-me", alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="replace-me", alias="OIDC_CLIENT_SECRET")
    oidc_issuer_url: str = Field(default="https://example.com/oidc", alias="OIDC_ISSUER_URL")
    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")
    backend_url: str = Field(default="http://localhost:8000", alias="BACKEND_URL")

    model_config = SettingsConfigDict(
        env_file=ENV_FILES or None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
