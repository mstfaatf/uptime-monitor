"""Application configuration from environment variables."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "development" (default, local HTTP) or "production" (forces COOKIE_SECURE, see below).
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/uptime"

    # JWT / session (used for signing cookie payload).
    # No default: the app must fail to start if this isn't set via env var or .env file.
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Cookie settings
    COOKIE_NAME: str = "session"
    COOKIE_HTTP_ONLY: bool = True
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_MAX_AGE: int = 60 * 60 * 24 * 7  # 7 days in seconds

    # Resend (transactional email — downtime/cert-expiry alerts, password reset). Unlike
    # JWT_SECRET, this has no fail-fast requirement: a missing key means email-sending degrades
    # safely to a log-and-skip no-op (see mail/client.py), not a security hole, so local dev
    # shouldn't need a real Resend account just to boot the app.
    RESEND_API_KEY: str | None = None
    # Sender identity for outgoing mail. Defaults to Resend's own sandbox address, which sends
    # without requiring a verified custom domain — fine for dev/testing. Override once a real
    # domain is verified with Resend.
    RESEND_FROM_EMAIL: str = "Uptime Monitor <onboarding@resend.dev>"

    @model_validator(mode="after")
    def _enforce_cookie_secure_in_production(self) -> "Settings":
        """ENVIRONMENT=production always gets a secure cookie, even if COOKIE_SECURE
        was left unset or mistakenly set to false — this is a non-negotiable rule
        (see CLAUDE.md), not just a default."""
        if self.ENVIRONMENT == "production":
            self.COOKIE_SECURE = True
        return self

    @property
    def asyncpg_database_url(self) -> str:
        """Plain postgresql:// DSN for a raw asyncpg connection (used for LISTEN/NOTIFY in
        realtime.py) — SQLAlchemy's async engine uses DATABASE_URL as-is (with the +asyncpg
        dialect suffix it needs), but asyncpg.connect() doesn't understand that suffix."""
        if self.DATABASE_URL.startswith("postgresql+asyncpg"):
            return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql", 1)
        return self.DATABASE_URL


settings = Settings()
