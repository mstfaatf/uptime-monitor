"""Target request customization (Phase 6, prompt 6.2): custom method/headers/basic-auth, and
keyword/content matching — all exercised against checker.check_url with a mocked
httpx.AsyncClient, same style as test_checker_redirects.py. The SSRF/redirect-revalidation
path itself is untouched by this feature (confirmed there, not re-tested here) — these tests
only cover what's new: which method/headers/auth reach client.request, and how a keyword
match/mismatch affects is_up/error.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx

from checker import check_url


def _fake_response(status_code, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.text = text
    resp.extensions = {}
    return resp


def _client():
    mock = MagicMock()
    mock.request = AsyncMock()
    return mock


async def test_explicit_method_is_used_once_with_no_head_get_fallback():
    """An explicit method disables the default HEAD-then-GET dance entirely — even a >=400
    response must not trigger a retry with a different method, unlike the method=None default."""
    client = _client()
    client.request.side_effect = [_fake_response(404)]

    result = await check_url(client, "https://example.com/x", dns_ms=1, method="POST")

    assert client.request.call_count == 1
    assert client.request.call_args.args[0] == "POST"
    assert result["status_code"] == 404
    assert result["is_up"] is False


async def test_custom_headers_are_passed_to_every_request():
    client = _client()
    client.request.side_effect = [_fake_response(200)]
    headers = {"X-Api-Key": "abc123"}

    await check_url(client, "https://example.com/x", dns_ms=1, method="GET", headers=headers)

    assert client.request.call_args.kwargs["headers"] == headers


async def test_basic_auth_is_passed_to_every_request():
    client = _client()
    client.request.side_effect = [_fake_response(200)]
    auth = httpx.BasicAuth("admin", "hunter2")

    await check_url(client, "https://example.com/x", dns_ms=1, method="GET", auth=auth)

    assert client.request.call_args.kwargs["auth"] is auth


async def test_default_method_none_still_does_head_then_get_fallback():
    """Regression check: passing headers/auth (both None by default) must not disturb the
    original HEAD-then-GET-on-failure default when no explicit method is configured."""
    client = _client()
    client.request.side_effect = [_fake_response(404), _fake_response(200)]

    result = await check_url(client, "https://example.com/x", dns_ms=1)

    assert client.request.call_count == 2
    assert client.request.call_args_list[0].args[0] == "HEAD"
    assert client.request.call_args_list[1].args[0] == "GET"
    assert result["is_up"] is True


async def test_keyword_match_with_no_explicit_method_uses_get_not_head():
    """Regression test for a real bug caught in live verification: with method=None (the
    common case — a target has a keyword_match but no explicitly chosen method), the default
    HEAD-first behavior must NOT apply, since HEAD's empty body can never satisfy a keyword
    condition regardless of status code — every keyword-matched check would otherwise fail
    every time with a spurious "not found", even when the live page genuinely contains it."""
    client = _client()
    client.request.side_effect = [_fake_response(200, text="status: healthy")]

    result = await check_url(client, "https://example.com/x", dns_ms=1, keyword_match="healthy")

    assert client.request.call_count == 1
    assert client.request.call_args.args[0] == "GET"
    assert result["is_up"] is True
    assert result["error"] is None


async def test_keyword_match_contains_mode_succeeds_when_present():
    client = _client()
    client.request.side_effect = [_fake_response(200, text="status: healthy")]

    result = await check_url(
        client, "https://example.com/x", dns_ms=1, method="GET", keyword_match="healthy"
    )

    assert result["is_up"] is True
    assert result["error"] is None


async def test_keyword_match_contains_mode_fails_when_absent():
    client = _client()
    client.request.side_effect = [_fake_response(200, text="status: down for maintenance")]

    result = await check_url(
        client, "https://example.com/x", dns_ms=1, method="GET", keyword_match="healthy"
    )

    assert result["is_up"] is False
    assert result["status_code"] == 200  # the HTTP request itself succeeded
    assert "Keyword match failed" in result["error"]
    assert "not found" in result["error"]
    assert '"healthy"' in result["error"]


async def test_keyword_match_not_contains_mode_succeeds_when_absent():
    client = _client()
    client.request.side_effect = [_fake_response(200, text="status: healthy")]

    result = await check_url(
        client,
        "https://example.com/x",
        dns_ms=1,
        method="GET",
        keyword_match="maintenance",
        keyword_match_mode="not_contains",
    )

    assert result["is_up"] is True
    assert result["error"] is None


async def test_keyword_match_not_contains_mode_fails_when_present():
    client = _client()
    client.request.side_effect = [_fake_response(200, text="down for maintenance")]

    result = await check_url(
        client,
        "https://example.com/x",
        dns_ms=1,
        method="GET",
        keyword_match="maintenance",
        keyword_match_mode="not_contains",
    )

    assert result["is_up"] is False
    assert "Keyword match failed" in result["error"]
    assert "unexpected" in result["error"]


async def test_keyword_match_is_not_checked_when_the_response_is_already_down():
    """A non-2xx/3xx status is already a failure — the keyword condition shouldn't even be
    consulted (and the error should stay the connection/HTTP-status reason, not a keyword one)."""
    client = _client()
    client.request.side_effect = [_fake_response(500, text="healthy")]  # keyword technically present

    result = await check_url(
        client, "https://example.com/x", dns_ms=1, method="GET", keyword_match="healthy"
    )

    assert result["is_up"] is False
    assert result["error"] is None  # no keyword-specific error — just a plain 500, not "up"
