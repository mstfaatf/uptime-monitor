"""Coverage for backend/mail/ (prompts 4.5-4.6): the Resend client wrapper and the plain-text
templates. Hermetic — no real Resend API calls. RESEND_API_KEY is controlled explicitly via
monkeypatch in each test rather than assumed absent from the ambient environment: a real key
may genuinely be configured in a developer's own .env (needed to actually verify alert
delivery by hand), and a test asserting on that ambient global would be fragile/wrong to do
so — it should control its own inputs."""

from unittest.mock import AsyncMock, patch

from config import settings
from mail import cert_expiry_alert_email, downtime_alert_email, downtime_recovery_email, password_reset_email, send_email


async def test_send_email_skips_without_an_api_key(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    sent = await send_email("nobody@example.com", "Subject", "Body")
    assert sent is False


async def test_send_email_sends_when_a_key_is_configured(monkeypatch):
    """Mocks the Resend SDK call itself — this asserts send_email calls it with the right
    shape, not that a real email is delivered (that's a live/manual verification concern, not
    something a hermetic test should attempt)."""
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_fake_key")
    with patch("mail.client.resend.Emails.send_async", new=AsyncMock(return_value={"id": "fake"})) as mock_send:
        sent = await send_email("nobody@example.com", "Subject", "Body text")
    assert sent is True
    mock_send.assert_awaited_once()
    call_args = mock_send.call_args[0][0]
    assert call_args["to"] == ["nobody@example.com"]
    assert call_args["subject"] == "Subject"
    assert call_args["text"] == "Body text"


async def test_send_email_returns_false_and_does_not_raise_when_resend_fails(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_fake_key")
    with patch("mail.client.resend.Emails.send_async", new=AsyncMock(side_effect=RuntimeError("boom"))):
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


def test_downtime_recovery_email_confirms_back_up_with_links():
    subject, body = downtime_recovery_email(
        target_label="My Site",
        target_url="https://example.com",
        region="local",
        checked_at="2026-09-13 19:05:00 UTC",
        detail_url="http://localhost:3000/dashboard/1",
        settings_url="http://localhost:3000/settings",
    )
    assert "back up" in subject
    assert "local" in subject
    assert "responding again" in body
    assert "http://localhost:3000/dashboard/1" in body
    assert "http://localhost:3000/settings" in body


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
