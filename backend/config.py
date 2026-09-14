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

    # CORS: comma-separated list of allowed origins (never "*" — allow_credentials=True below
    # means a wildcard is both rejected by browsers and a real security hole if it weren't).
    # Defaults to the local frontend dev server; set to the real Vercel domain(s) in production.
    CORS_ORIGINS: str = "http://localhost:3000"

    # Resend (transactional email — downtime/cert-expiry alerts, password reset). Unlike
    # JWT_SECRET, this has no fail-fast requirement: a missing key means email-sending degrades
    # safely to a log-and-skip no-op (see mail/client.py), not a security hole, so local dev
    # shouldn't need a real Resend account just to boot the app.
    RESEND_API_KEY: str | None = None
    # Sender identity for outgoing mail. Defaults to Resend's own sandbox address, which sends
    # without requiring a verified custom domain — fine for dev/testing. Override once a real
    # domain is verified with Resend.
    RESEND_FROM_EMAIL: str = "Uptime Monitor <onboarding@resend.dev>"

    # Base URL the backend uses to build links in outgoing email (detail page, settings page,
    # password reset) — mail/templates.py takes fully-built URLs as arguments rather than
    # knowing about frontend routing itself, so something has to own building them; that's
    # realtime.py's alerting logic, using this setting. Same origin CORS already allows
    # (main.py), just not previously named as a reusable setting.
    FRONTEND_URL: str = "http://localhost:3000"

    # Alerting (backend/realtime.py's NOTIFY handler — see the Phase 4 design report).
    # A flapping target can't re-trigger a downtime email faster than this, regardless of how
    # many genuine up/down transitions happen in between. 900s matches worker/backoff.py's own
    # cap — the same point this project's backoff curve already treats a target as more than a
    # transient blip.
    DOWNTIME_ALERT_COOLDOWN_SECONDS: int = 900
    # Mirrors the frontend's lib/thresholds.ts CERT_EXPIRY_WARN_DAYS — same "deliberately
    # duplicated across services, kept in sync by hand" tradeoff as worker/ssrf.py vs
    # backend/security/ssrf.py, since the frontend threshold isn't reachable from Python.
    CERT_EXPIRY_WARN_DAYS: int = 14
    # Once a cert is within CERT_EXPIRY_WARN_DAYS and unrenewed, re-remind at most this often
    # rather than one-shot-forever (someone who hasn't renewed after the first email may still
    # miss it) or on every single check (spam for a slow-moving, monotonic signal).
    CERT_EXPIRY_REMINDER_COOLDOWN_DAYS: int = 3

    @model_validator(mode="after")
    def _enforce_secure_cookie_settings_in_production(self) -> "Settings":
        """ENVIRONMENT=production always gets a secure, cross-site-capable cookie, even if
        COOKIE_SECURE/COOKIE_SAMESITE were left unset or mistakenly set otherwise — this is a
        non-negotiable rule (see CLAUDE.md), not just a default.

        COOKIE_SAMESITE="none" is required (not just permitted) in production because the
        frontend (Vercel) and backend (Railway) are on different origins — a "lax" cookie is
        silently dropped on cross-site requests, which would break login without any visible
        error. Browsers reject SameSite=None unless Secure is also set, which COOKIE_SECURE's
        own override above already guarantees runs first in this same validator.
        """
        if self.ENVIRONMENT == "production":
            self.COOKIE_SECURE = True
            self.COOKIE_SAMESITE = "none"
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS parsed into a list for CORSMiddleware's allow_origins — comma-separated
        so it's a plain string in Railway's/any dashboard's env var UI, not JSON-in-a-string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def asyncpg_database_url(self) -> str:
        """Plain postgresql:// DSN for a raw asyncpg connection (used for LISTEN/NOTIFY in
        realtime.py) — SQLAlchemy's async engine uses DATABASE_URL as-is (with the +asyncpg
        dialect suffix it needs), but asyncpg.connect() doesn't understand that suffix."""
        if self.DATABASE_URL.startswith("postgresql+asyncpg"):
            return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql", 1)
        return self.DATABASE_URL


settings = Settings()
