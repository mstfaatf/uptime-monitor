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

    @model_validator(mode="after")
    def _enforce_cookie_secure_in_production(self) -> "Settings":
        """ENVIRONMENT=production always gets a secure cookie, even if COOKIE_SECURE
        was left unset or mistakenly set to false — this is a non-negotiable rule
        (see CLAUDE.md), not just a default."""
        if self.ENVIRONMENT == "production":
            self.COOKIE_SECURE = True
        return self


settings = Settings()
