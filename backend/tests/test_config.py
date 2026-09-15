"""JWT_SECRET fail-fast: config.py's Settings() must refuse to instantiate without it.

This is the same validation `settings = Settings()` runs at import time in config.py, which
is what actually makes the app fail to start — tested here directly against the Settings
class (bypassing the already-imported module-level singleton) rather than via a subprocess,
since that's the exact mechanism responsible for the fail-fast behavior.
"""

import pytest
from pydantic import ValidationError

from config import Settings


def test_missing_jwt_secret_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        # _env_file=None: don't fall back to a real .env file that might happen to set
        # JWT_SECRET on whichever machine runs this test.
        Settings(_env_file=None)
    assert "JWT_SECRET" in str(exc_info.value)


def test_jwt_secret_present_succeeds(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    settings = Settings(_env_file=None)
    assert settings.JWT_SECRET == "some-secret"


def test_environment_production_forces_cookie_secure(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("COOKIE_SECURE", "false")  # deliberately wrong — must be overridden
    settings = Settings(_env_file=None)
    assert settings.COOKIE_SECURE is True


def test_environment_development_leaves_cookie_secure_false_by_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.COOKIE_SECURE is False


def test_environment_production_forces_cookie_samesite_none(monkeypatch):
    # Frontend (Vercel) and backend (Railway) are different origins in production — SameSite
    # must be "none" (never "lax") or the browser silently drops the cookie cross-site.
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("COOKIE_SAMESITE", "lax")  # deliberately wrong — must be overridden
    settings = Settings(_env_file=None)
    assert settings.COOKIE_SAMESITE == "none"


def test_environment_development_leaves_cookie_samesite_lax_by_default(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("COOKIE_SAMESITE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.COOKIE_SAMESITE == "lax"


def test_cors_origins_list_defaults_to_local_frontend(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.cors_origins_list == ["http://localhost:3000"]


def test_cors_origins_list_parses_comma_separated_values(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://app.vercel.app, https://custom-domain.com ,https://another.app"
    )
    settings = Settings(_env_file=None)
    assert settings.cors_origins_list == [
        "https://app.vercel.app",
        "https://custom-domain.com",
        "https://another.app",
    ]


def test_listen_asyncpg_url_falls_back_to_database_url_when_unset(monkeypatch):
    # Local dev / Docker Compose: no pooler, so LISTEN_DATABASE_URL is never set and the
    # listener must keep using DATABASE_URL exactly as before this setting existed.
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/uptime")
    monkeypatch.delenv("LISTEN_DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.listen_asyncpg_url == "postgresql://postgres:postgres@db:5432/uptime"


def test_listen_asyncpg_url_prefers_listen_database_url_when_set(monkeypatch):
    # Production: DATABASE_URL is Neon's pooled endpoint (fine for ordinary queries, but
    # doesn't reliably deliver NOTIFYs to a LISTEN session); LISTEN_DATABASE_URL points at
    # Neon's direct endpoint instead, and must win.
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@ep-example-pooler.us-east-2.aws.neon.tech/db?ssl=require",
    )
    monkeypatch.setenv(
        "LISTEN_DATABASE_URL",
        "postgresql+asyncpg://user:pass@ep-example.us-east-2.aws.neon.tech/db?ssl=require",
    )
    settings = Settings(_env_file=None)
    assert (
        settings.listen_asyncpg_url
        == "postgresql://user:pass@ep-example.us-east-2.aws.neon.tech/db?ssl=require"
    )


def test_listen_asyncpg_url_strips_asyncpg_dialect_suffix(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "some-secret")
    monkeypatch.setenv("LISTEN_DATABASE_URL", "postgresql+asyncpg://a:b@host/db?ssl=require")
    settings = Settings(_env_file=None)
    assert settings.listen_asyncpg_url == "postgresql://a:b@host/db?ssl=require"
