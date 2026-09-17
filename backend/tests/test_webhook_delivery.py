"""Coverage for backend/webhooks.py: payload construction, HMAC signing, and send_webhook's
delivery/SSRF/failure behavior. Hermetic — httpx is mocked throughout, no real network calls.
Mirrors test_mail.py's approach for send_email (mock the outbound client, assert on how it was
called), and worker/tests' convention of using real IP literals (not made-up hostnames) for
SSRF cases, since is_url_blocked() isn't mocked and does a real DNS lookup.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from webhooks import SIGNATURE_HEADER, build_webhook_payload, send_webhook


class _FakeTarget:
    def __init__(self, id=1, name=None, url="https://example.com"):
        self.id = id
        self.name = name
        self.url = url


class _FakeCheck:
    def __init__(self, checked_at, error=None, tls_cert_expires_at=None, tls_cert_issuer=None):
        self.checked_at = checked_at
        self.error = error
        self.tls_cert_expires_at = tls_cert_expires_at
        self.tls_cert_issuer = tls_cert_issuer


def _mock_httpx_client(response=None, raises=None):
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    if raises is not None:
        mock_client.post = AsyncMock(side_effect=raises)
    else:
        mock_client.post = AsyncMock(return_value=response)
    return mock_client


def _fake_response(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    return resp


# --- build_webhook_payload ---


def test_build_webhook_payload_basic_shape():
    target = _FakeTarget(id=42, name="My Site", url="https://example.com")
    check = _FakeCheck(checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc), error="Connection timed out")

    payload = build_webhook_payload("target.down", target, "us-east", check, "http://localhost:3000/dashboard/42")

    assert payload["event"] == "target.down"
    assert payload["target"] == {"id": 42, "name": "My Site", "url": "https://example.com"}
    assert payload["region"] == "us-east"
    assert payload["checked_at"] == "2026-01-01T00:00:00+00:00"
    assert payload["error"] == "Connection timed out"
    assert payload["cert"] is None
    assert payload["detail_url"] == "http://localhost:3000/dashboard/42"


def test_build_webhook_payload_includes_cert_when_present():
    target = _FakeTarget()
    # +1 hour of margin: days_remaining is computed a moment after expires_at is fixed here,
    # and timedelta.days truncates — "9 days minus a few milliseconds" reads as 8, not 9,
    # deterministically, not just occasionally. The margin keeps this assertion meaningful
    # without being sensitive to real test-execution timing.
    expires_at = datetime.now(timezone.utc) + timedelta(days=9, hours=1)
    check = _FakeCheck(checked_at=datetime.now(timezone.utc), tls_cert_expires_at=expires_at, tls_cert_issuer="CN=R3")

    payload = build_webhook_payload("target.cert_expiring", target, "local", check, "http://x/dashboard/1")

    assert payload["cert"]["expires_at"] == expires_at.isoformat()
    assert payload["cert"]["days_remaining"] == 9
    assert payload["cert"]["issuer"] == "CN=R3"


# --- send_webhook ---


async def test_send_webhook_blocked_at_send_time_for_private_ip():
    """The scenario the prompt explicitly asks for: a webhook URL pointed at a private IP is
    rejected at send time, not just at creation — real DNS-rebinding defense, exercised here
    with an IP literal (no real DNS lookup needed, matching the rest of this codebase's SSRF
    test convention)."""
    with patch("webhooks.httpx.AsyncClient") as mock_client_cls:
        sent = await send_webhook("http://127.0.0.1:9999/hook", "secret", {"event": "target.down"})

    assert sent is False
    mock_client_cls.assert_not_called()  # never even attempted the HTTP request


async def test_send_webhook_blocked_for_link_local_metadata_address():
    with patch("webhooks.httpx.AsyncClient") as mock_client_cls:
        sent = await send_webhook("http://169.254.169.254/steal", "secret", {"event": "target.down"})

    assert sent is False
    mock_client_cls.assert_not_called()


async def test_send_webhook_succeeds_and_signs_the_payload():
    payload = {"event": "target.down", "target": {"id": 1}}
    mock_client = _mock_httpx_client(_fake_response(200))

    with patch("webhooks.httpx.AsyncClient", return_value=mock_client):
        sent = await send_webhook("http://8.8.8.8/hook", "my-secret", payload)

    assert sent is True
    mock_client.post.assert_awaited_once()
    call = mock_client.post.call_args
    assert call.args[0] == "http://8.8.8.8/hook"
    sent_body = call.kwargs["content"]
    assert json.loads(sent_body) == payload

    expected_signature = "sha256=" + hmac.new(b"my-secret", sent_body, hashlib.sha256).hexdigest()
    assert call.kwargs["headers"][SIGNATURE_HEADER] == expected_signature


async def test_send_webhook_uses_a_different_signature_for_a_different_secret():
    mock_client = _mock_httpx_client(_fake_response(200))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client):
        await send_webhook("http://8.8.8.8/hook", "secret-a", {"x": 1})
    sig_a = mock_client.post.call_args.kwargs["headers"][SIGNATURE_HEADER]

    mock_client2 = _mock_httpx_client(_fake_response(200))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client2):
        await send_webhook("http://8.8.8.8/hook", "secret-b", {"x": 1})
    sig_b = mock_client2.post.call_args.kwargs["headers"][SIGNATURE_HEADER]

    assert sig_a != sig_b


async def test_send_webhook_does_not_follow_redirects_and_treats_3xx_as_failure():
    mock_client = _mock_httpx_client(_fake_response(302))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client) as mock_client_cls:
        sent = await send_webhook("http://8.8.8.8/hook", "secret", {"event": "target.down"})

    assert sent is False
    # follow_redirects=False was passed to the client constructor — a 3xx is simply not chased.
    assert mock_client_cls.call_args.kwargs["follow_redirects"] is False
    mock_client.post.assert_awaited_once()  # exactly one request — no second hop attempted


async def test_send_webhook_returns_false_on_non_2xx():
    mock_client = _mock_httpx_client(_fake_response(500))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client):
        sent = await send_webhook("http://8.8.8.8/hook", "secret", {"event": "target.down"})
    assert sent is False


async def test_send_webhook_returns_false_and_does_not_raise_on_connection_error():
    mock_client = _mock_httpx_client(raises=ConnectionError("boom"))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client):
        sent = await send_webhook("http://8.8.8.8/hook", "secret", {"event": "target.down"})
    assert sent is False


async def test_send_webhook_uses_a_short_timeout():
    mock_client = _mock_httpx_client(_fake_response(200))
    with patch("webhooks.httpx.AsyncClient", return_value=mock_client) as mock_client_cls:
        await send_webhook("http://8.8.8.8/hook", "secret", {"event": "target.down"})
    assert mock_client_cls.call_args.kwargs["timeout"] == 5
