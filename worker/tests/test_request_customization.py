"""Target request customization (Phase 6, prompt 6.2): custom method/headers/basic-auth, and
keyword/content matching — all exercised against checker.check_url with a mocked
httpx.AsyncClient, same style as test_checker_redirects.py. The SSRF/redirect-revalidation
path itself is untouched by this feature (confirmed there, not re-tested here) — these tests
only cover what's new: which method/headers/auth reach client.request, how a keyword
match/mismatch affects is_up/error, and that headers/auth are dropped on a cross-host redirect
(a credential-leak fix — see _redirect_crosses_host in checker.py).
"""

from unittest.mock import AsyncMock, MagicMock

import httpx

from checker import check_url


def _fake_response(status_code, text="", location=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Location": location} if location else {}
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


async def test_same_host_redirect_keeps_headers_and_auth():
    """A redirect that stays on the same host (e.g. http:// -> https://, or a different path)
    is exactly the case httpx's own follow_redirects=True would also keep credentials for.
    Uses real IP literals (matching test_checker_redirects.py's own convention), not domain
    names — is_url_blocked() isn't mocked here and does a real socket.getaddrinfo() call on
    each redirect hop's target, so a made-up hostname would fail DNS resolution and get
    SSRF-blocked rather than actually exercising the redirect-following logic under test."""
    client = _client()
    auth = httpx.BasicAuth("admin", "hunter2")
    headers = {"X-Api-Key": "abc123"}
    client.request.side_effect = [
        _fake_response(302, location="https://1.1.1.1/final"),
        _fake_response(200),
    ]

    await check_url(client, "https://1.1.1.1/start", dns_ms=1, method="GET", headers=headers, auth=auth)

    assert client.request.call_count == 2
    assert client.request.call_args_list[1].kwargs["headers"] == headers
    assert client.request.call_args_list[1].kwargs["auth"] is auth


async def test_cross_host_redirect_drops_headers_and_auth():
    """A real credential-leak vector: httpx's own follow_redirects=True strips Authorization
    on a cross-origin redirect automatically, but this manual redirect loop (needed for
    per-hop SSRF revalidation) bypasses that built-in protection entirely unless replicated
    here — without this, a target's basic-auth password or a secret-bearing custom header
    would be forwarded to whatever third-party host a 3xx response happens to name."""
    client = _client()
    auth = httpx.BasicAuth("admin", "hunter2")
    headers = {"X-Api-Key": "abc123"}
    client.request.side_effect = [
        _fake_response(302, location="https://8.8.8.8/steal"),
        _fake_response(200),
    ]

    await check_url(client, "https://1.1.1.1/start", dns_ms=1, method="GET", headers=headers, auth=auth)

    assert client.request.call_count == 2
    # First hop (the user's own configured target) still gets the real credentials.
    assert client.request.call_args_list[0].kwargs["headers"] == headers
    assert client.request.call_args_list[0].kwargs["auth"] is auth
    # Second hop (a different host) must not receive them.
    assert client.request.call_args_list[1].kwargs["headers"] is None
    assert client.request.call_args_list[1].kwargs["auth"] is None


async def test_cross_host_redirect_credentials_stay_dropped_even_if_redirected_back():
    """Once dropped, credentials are not restored even if a later hop redirects back to the
    original host — a deliberately conservative choice rather than re-deriving trust hop by
    hop against a moving target."""
    client = _client()
    auth = httpx.BasicAuth("admin", "hunter2")
    client.request.side_effect = [
        _fake_response(302, location="https://8.8.8.8/bounce"),
        _fake_response(302, location="https://1.1.1.1/back"),
        _fake_response(200),
    ]

    await check_url(client, "https://1.1.1.1/start", dns_ms=1, method="GET", auth=auth)

    assert client.request.call_count == 3
    assert client.request.call_args_list[0].kwargs["auth"] is auth
    assert client.request.call_args_list[1].kwargs["auth"] is None
    assert client.request.call_args_list[2].kwargs["auth"] is None  # still dropped


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
