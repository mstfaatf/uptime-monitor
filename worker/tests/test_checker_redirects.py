"""Tests for the redirect-bypass fix in worker/checker.py (Phase 0 prompt 0.4), re-verified
against the async httpx rewrite (Phase 1 prompt 1.2).

Before the fix, following redirects natively (requests' allow_redirects=True, or httpx's
follow_redirects=True) would follow a redirect without ever re-validating it against the SSRF
blocklist — a target could pass its SSRF check and then 302 to a blocked address (e.g. a cloud
metadata IP) and have it fetched anyway. checker.py follows redirects manually instead, via a
shared httpx.AsyncClient, re-checking each hop's Location header first.

All HTTP is mocked (unittest.mock, no real network) — these are unit tests of the redirect
logic, not integration tests against a real server or client.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from checker import MAX_REDIRECTS, check_url


def _fake_response(status_code, location=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Location": location} if location else {}
    return resp


@pytest.fixture
def client():
    """A mocked httpx.AsyncClient stand-in — only .request() is ever awaited by checker.py."""
    mock = MagicMock()
    mock.request = AsyncMock()
    return mock


async def test_redirect_to_blocked_address_is_not_followed(client):
    """A target that starts out fine but 302s to a blocked IP must be caught, and the
    blocked address itself must never actually be requested."""
    client.request.side_effect = [_fake_response(302, "http://169.254.169.254/latest/meta-data/")]

    result = await check_url(client, "https://8.8.8.8/")

    assert result["is_up"] is False
    assert "blocked" in result["error"].lower()
    assert client.request.call_count == 1  # the blocked hop was never fetched


async def test_normal_redirect_chain_is_followed(client):
    client.request.side_effect = [
        _fake_response(302, "https://1.1.1.1/"),
        _fake_response(200),
    ]

    result = await check_url(client, "https://8.8.8.8/")

    assert result["is_up"] is True
    assert result["status_code"] == 200


async def test_too_many_redirects_is_treated_as_failure(client):
    # Always redirects, never resolves — should stop at MAX_REDIRECTS, not loop forever.
    client.request.side_effect = [_fake_response(302, "https://1.1.1.1/next") for _ in range(MAX_REDIRECTS + 2)]

    result = await check_url(client, "https://8.8.8.8/")

    assert result["is_up"] is False
    assert "too many redirects" in result["error"].lower()
