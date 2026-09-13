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
    # Identifies which region this worker instance is checking from — tagged onto log lines
    # now, and onto checks rows once the Phase 2 multi-region schema migration lands. Defaults
    # to "local" for single-instance dev; per the Phase 2 design report, this should become a
    # required field (no default) once a real multi-region deployment is in view, so a
    # misconfigured worker can't silently report under the wrong (or no) region.
    REGION: str = "local"

    @property
    def asyncpg_database_url(self) -> str:
        return _strip_asyncpg_dialect_suffix(self.DATABASE_URL)


settings = Settings()
