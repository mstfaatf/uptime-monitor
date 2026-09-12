"""Tests for the redirect-bypass fix in worker/checker.py (Phase 0 prompt 0.4).

Before the fix, requests.head/get(..., allow_redirects=True) followed redirects without ever
re-validating them against the SSRF blocklist — a target could pass its SSRF check and then
302 to a blocked address (e.g. a cloud metadata IP) and have it fetched anyway. checker.py now
follows redirects manually, re-checking each hop's Location header first.

All HTTP is mocked (unittest.mock, no new dependency) — these are unit tests of the redirect
logic, not integration tests against a real server.
"""

from unittest.mock import MagicMock, patch

from checker import MAX_REDIRECTS, check_url


def _fake_response(status_code, location=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Location": location} if location else {}
    return resp


def test_redirect_to_blocked_address_is_not_followed():
    """A target that starts out fine but 302s to a blocked IP must be caught, and the
    blocked address itself must never actually be requested."""
    responses = [_fake_response(302, "http://169.254.169.254/latest/meta-data/")]

    with patch("checker.requests.request", side_effect=responses) as mock_request:
        result = check_url("https://8.8.8.8/")

    assert result["is_up"] is False
    assert "blocked" in result["error"].lower()
    assert mock_request.call_count == 1  # the blocked hop was never fetched


def test_normal_redirect_chain_is_followed():
    responses = [
        _fake_response(302, "https://1.1.1.1/"),
        _fake_response(200),
    ]
    with patch("checker.requests.request", side_effect=responses):
        result = check_url("https://8.8.8.8/")

    assert result["is_up"] is True
    assert result["status_code"] == 200


def test_too_many_redirects_is_treated_as_failure():
    # Always redirects, never resolves — should stop at MAX_REDIRECTS, not loop forever.
    responses = [_fake_response(302, "https://1.1.1.1/next") for _ in range(MAX_REDIRECTS + 2)]
    with patch("checker.requests.request", side_effect=responses):
        result = check_url("https://8.8.8.8/")

    assert result["is_up"] is False
    assert "too many redirects" in result["error"].lower()
