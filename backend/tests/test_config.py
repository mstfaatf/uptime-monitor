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
