# backend/app/core/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Points to .../Hyperion/backend
BASE_DIR = Path(__file__).resolve().parents[2]
DB_FILE = (BASE_DIR / "dev.db").as_posix()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )

    # App (async) and Alembic (sync) must be the same absolute file
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DB_FILE}"
    SYNC_DATABASE_URL: str = f"sqlite:///{DB_FILE}"

    APP_ENV: str = "dev"
    GITHUB_TOKEN: str = ""
    SLACK_BOT_TOKEN: str = ""
    RUNS_HMAC_KEY: str = ""

settings = Settings()