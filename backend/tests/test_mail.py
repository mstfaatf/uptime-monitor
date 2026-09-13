"""Coverage for backend/mail/ (prompt 4.5): the Resend client wrapper and the three plain-text
templates. Hermetic — no real Resend API calls (RESEND_API_KEY is unset in the test
environment, which is exactly the no-op path this suite asserts)."""

from config import settings
from mail import cert_expiry_alert_email, downtime_alert_email, password_reset_email, send_email


async def test_send_email_skips_without_an_api_key():
    """The test environment never sets RESEND_API_KEY — this is the real "safe degraded state"
    path, not a mock standing in for it."""
    assert settings.RESEND_API_KEY is None
    sent = await send_email("nobody@example.com", "Subject", "Body")
    assert sent is False


def test_downtime_alert_email_includes_target_error_and_links():
    subject, body = downtime_alert_email(
        target_label="My Site",
        target_url="https://example.com",
        region="local",
        checked_at="2026-09-13 19:00:00 UTC",
        error="Connection timed out",
        detail_url="http://localhost:3000/dashboard/1",
        settings_url="http://localhost:3000/settings",
    )
    assert "My Site" in subject
    assert "local" in subject
    assert "https://example.com" in body
    assert "Connection timed out" in body
    assert "http://localhost:3000/dashboard/1" in body
    assert "http://localhost:3000/settings" in body


def test_downtime_alert_email_does_not_duplicate_url_when_target_has_no_name():
    _, body = downtime_alert_email(
        target_label="https://example.com",
        target_url="https://example.com",
        region="eu-west",
        checked_at="2026-09-13 19:00:00 UTC",
        error=None,
        detail_url="http://localhost:3000/dashboard/1",
        settings_url="http://localhost:3000/settings",
    )
    assert body.count("https://example.com") == 1
    assert "No response" in body  # the null-error fallback


def test_cert_expiry_alert_email_includes_days_expiry_and_issuer():
    subject, body = cert_expiry_alert_email(
        target_label="My Site",
        target_url="https://example.com",
        region="local",
        days_remaining=9,
        expires_at="2026-09-22 12:46:33 UTC",
        issuer="CN=R3, O=Let's Encrypt, C=US",
        detail_url="http://localhost:3000/dashboard/1",
        settings_url="http://localhost:3000/settings",
    )
    assert "9" in subject
    assert "9" in body
    assert "2026-09-22 12:46:33 UTC" in body
    assert "Let's Encrypt" in body
    assert "http://localhost:3000/settings" in body


def test_password_reset_email_includes_link_and_expiry_and_no_settings_link():
    subject, body = password_reset_email(
        reset_url="http://localhost:3000/reset-password?token=abc123", expires_in_minutes=60
    )
    assert "Reset" in subject
    assert "http://localhost:3000/reset-password?token=abc123" in body
    assert "60 minutes" in body
    assert "/settings" not in body  # not an alert type, no alert-preferences footer
