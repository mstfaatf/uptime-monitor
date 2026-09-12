"""Worker configuration from environment variables (same DATABASE_URL pattern as backend)."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_asyncpg_dialect_suffix(url: str) -> str:
    """Convert SQLAlchemy-style postgresql+asyncpg:// to plain postgresql:// — the worker
    talks to the driver (asyncpg) directly via raw queries, not through SQLAlchemy, and
    asyncpg's own DSN parser doesn't understand the "+asyncpg" dialect suffix."""
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime"
    CHECK_INTERVAL_SECONDS: int = 300
    HTTP_TIMEOUT_SECONDS: int = 10
    # Set to "false" only for local/dev if SSL verification fails (insecure).
    HTTP_VERIFY_SSL: bool = True

    @property
    def asyncpg_database_url(self) -> str:
        return _strip_asyncpg_dialect_suffix(self.DATABASE_URL)


settings = Settings()
