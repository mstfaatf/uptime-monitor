"""Worker configuration from environment variables (same DATABASE_URL pattern as backend)."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


def _sync_database_url(url: str) -> str:
    """Convert postgresql+asyncpg to postgresql for sync driver (psycopg2)."""
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime"
    CHECK_INTERVAL_SECONDS: int = 300
    HTTP_TIMEOUT_SECONDS: int = 10

    @property
    def sync_database_url(self) -> str:
        return _sync_database_url(self.DATABASE_URL)


settings = Settings()
