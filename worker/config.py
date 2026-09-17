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

    # Must be set to the exact same value as the backend's CREDENTIAL_ENCRYPTION_KEY — this
    # worker decrypts basic-auth credentials the backend encrypted at target-creation/edit
    # time (see crypto.py). No default, same required/fail-fast treatment as the backend's
    # copy of this setting (which itself mirrors JWT_SECRET's treatment) — a missing key here
    # would otherwise surface as a confusing crash on the first check of any target with
    # basic auth configured, rather than at startup.
    CREDENTIAL_ENCRYPTION_KEY: str

    # How many days of raw checks history to keep before a background sweep prunes it (Phase
    # 6, prompt 6.8 — see retention.py). 90 matches the frontend detail page's existing 90-day
    # heatmap window, so pruning never silently breaks a UI feature that already reads that far
    # back. Also read by the backend (backend/config.py's own copy of this setting, same
    # "duplicated across independently-deployed services, kept in sync by hand" tradeoff
    # already established for SSRF/NOTIFY_CHANNEL/etc.) so a compliance export can note when a
    # requested range predates what's actually still on disk.
    CHECKS_RETENTION_DAYS: int = 90

    @property
    def asyncpg_database_url(self) -> str:
        return _strip_asyncpg_dialect_suffix(self.DATABASE_URL)


settings = Settings()
