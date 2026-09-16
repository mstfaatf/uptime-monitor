"""Perform a single HTTP check: HEAD first, retry once with GET if HEAD fails or status >= 400
(the default — a target can instead configure an explicit method, custom headers, basic auth,
and/or a keyword/content match; see check_url's docstring, Phase 6 prompt 6.2).

Also captures, as a side effect of the same request(s) — no extra connections or lookups:
- a DNS/TCP/TLS/TTFB timing breakdown (dns_ms piggybacks on the existing SSRF resolution call;
  tcp_ms/tls_ms/ttfb_ms come from httpx's low-level trace extension), and
- TLS certificate expiry/issuer for https:// targets, read off the same TLS handshake.

Both are captured against the final hop of a redirect chain, never an intermediate one — see
_follow_with_ssrf_check, which only extracts them from the request that produced the response
actually being returned.
"""

import asyncio
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

from ssrf import is_url_blocked

MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


class RedirectValidationError(Exception):
    """Raised when a redirect chain can't be safely followed (SSRF-blocked hop, or too many hops)."""


@dataclass
class _HopResult:
    """The response that was actually used, plus timing/cert data for that specific hop only."""

    response: httpx.Response
    dns_ms: int | None
    tcp_ms: int | None
    tls_ms: int | None
    ttfb_ms: int | None
    tls_cert_expires_at: datetime | None
    tls_cert_issuer: str | None


def _collect_trace(events: dict[str, float]):
    """Return an httpx trace-extension callback that records a perf_counter() timestamp for
    each named phase boundary httpcore reports (connect_tcp/start_tls/send/receive ...)."""

    async def trace(name: str, info: dict) -> None:
        events[name] = time.perf_counter()

    return trace


def _extract_timings(events: dict[str, float]) -> tuple[int | None, int | None, int | None]:
    """Turn raw trace-event timestamps into tcp_ms/tls_ms/ttfb_ms. Any phase the request never
    reached (e.g. no TLS on a plain http:// request) is left as None."""

    def phase_ms(started_key: str, complete_key: str) -> int | None:
        if started_key in events and complete_key in events:
            return round((events[complete_key] - events[started_key]) * 1000)
        return None

    tcp_ms = phase_ms("connection.connect_tcp.started", "connection.connect_tcp.complete")
    tls_ms = phase_ms("connection.start_tls.started", "connection.start_tls.complete")

    # TTFB: time from "request fully sent" to "response headers fully received." httpcore's
    # trace doesn't expose a finer "first byte" boundary than this, but the actual network
    # wait happens inside receive_response_headers (started ~= request-sent time), so this is
    # an accurate proxy, not just an approximation of convenience.
    send_done = events.get("http11.send_request_body.complete") or events.get(
        "http11.send_request_headers.complete"
    )
    recv_done = events.get("http11.receive_response_headers.complete")
    ttfb_ms = round((recv_done - send_done) * 1000) if send_done is not None and recv_done is not None else None

    return tcp_ms, tls_ms, ttfb_ms


def _extract_cert(response: httpx.Response, url: str) -> tuple[datetime | None, str | None]:
    """Read the peer certificate off the TLS socket already open for this response — no
    second connection. https:// only; anything else (including any failure to read the cert)
    returns (None, None) rather than raising, since this is enrichment, not the check itself."""
    if not url.lower().startswith("https://"):
        return None, None
    try:
        network_stream = response.extensions.get("network_stream")
        if network_stream is None:
            return None, None
        ssl_object = network_stream.get_extra_info("ssl_object")
        if ssl_object is None:
            return None, None
        cert = ssl_object.getpeercert()
        if not cert:
            return None, None
        expires_at = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
        issuer = ", ".join("=".join(pair) for rdn in cert.get("issuer", ()) for pair in rdn) or None
        return expires_at, issuer
    except Exception:
        return None, None


async def _follow_with_ssrf_check(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    initial_dns_ms: int | None,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
) -> _HopResult:
    """
    Perform `method` against `url`, following redirects manually (follow_redirects=False) so
    each hop's target can be re-validated against the SSRF blocklist before it's followed.
    follow_redirects=True would follow a redirect to a blocked address without ever re-checking
    it — a target can pass the SSRF check at creation/check time but 3xx-redirect to e.g.
    http://169.254.169.254/ or http://127.0.0.1/, bypassing the guard entirely.

    headers/auth are a target's optional request customization (Phase 6, prompt 6.2) — passed
    straight through to httpx on every hop, same as method. They have no bearing on the SSRF
    check itself: every redirect hop's Location is still resolved and validated exactly as
    before, regardless of what headers/auth are configured.

    Returns a _HopResult built only from the final hop's response — timing/cert data from
    intermediate redirect hops is discarded, since it describes a connection we didn't end up
    using.
    """
    current_url = url
    current_dns_ms = initial_dns_ms
    for _ in range(MAX_REDIRECTS + 1):
        trace_events: dict[str, float] = {}
        resp = await client.request(
            method,
            current_url,
            follow_redirects=False,
            extensions={"trace": _collect_trace(trace_events)},
            headers=headers,
            auth=auth,
        )
        if resp.status_code in _REDIRECT_STATUS_CODES and "Location" in resp.headers:
            next_url = urljoin(current_url, resp.headers["Location"])
            # is_url_blocked() does a blocking socket.getaddrinfo() call — run it off the event
            # loop so one redirect-hop resolution doesn't stall every other in-flight check.
            dns_start = time.perf_counter()
            blocked, reason = await asyncio.to_thread(is_url_blocked, next_url)
            current_dns_ms = int((time.perf_counter() - dns_start) * 1000)
            if blocked:
                raise RedirectValidationError(f"Redirect target blocked: {reason}")
            current_url = next_url
            continue
        tcp_ms, tls_ms, ttfb_ms = _extract_timings(trace_events)
        cert_expires_at, cert_issuer = _extract_cert(resp, current_url)
        return _HopResult(resp, current_dns_ms, tcp_ms, tls_ms, ttfb_ms, cert_expires_at, cert_issuer)
    raise RedirectValidationError(f"Too many redirects (>{MAX_REDIRECTS})")


def _check_keyword_match(body_text: str, keyword_match: str, keyword_match_mode: str) -> str | None:
    """Return an error string if the configured keyword condition fails, else None (the match
    condition holds). Distinctly prefixed ("Keyword match failed: ...") so this is never
    confused with a connection failure when read off checks.error later — the same convention
    this module already uses for SSRF/redirect blocks ("Redirect target blocked: ...",
    "Resolved to blocked IP: ..." in ssrf.py)."""
    found = keyword_match in body_text
    if keyword_match_mode == "not_contains":
        if found:
            return f'Keyword match failed: unexpected "{keyword_match}" found in response body'
        return None
    if not found:
        return f'Keyword match failed: expected "{keyword_match}" not found in response body'
    return None


async def check_url(
    client: httpx.AsyncClient,
    url: str,
    dns_ms: int | None,
    method: str | None = None,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
    keyword_match: str | None = None,
    keyword_match_mode: str = "contains",
) -> dict:
    """
    method=None (the default): try HEAD first; if HEAD fails or returns >= 400, retry once
    with GET — today's original behavior, unchanged, UNLESS keyword_match is also set (see
    below), in which case method=None means "GET" instead — HEAD's empty body can never
    satisfy a keyword condition regardless of its status code, so trying HEAD first there
    would silently fail every keyword-matched check on the most common configuration (a target
    with a keyword_match but no explicitly chosen method). An explicit method (GET/POST/HEAD,
    a target's request-customization choice — see backend/routers/targets.py's
    ALLOWED_REQUEST_METHODS) always disables the HEAD-then-GET fallback entirely and is used
    exactly once: the user chose it deliberately (e.g. POST against a health endpoint that
    doesn't support HEAD), so silently trying something else would be surprising, not helpful.

    headers/auth are passed straight through to every request (see _follow_with_ssrf_check).

    keyword_match/keyword_match_mode: after a response that would otherwise count as "up"
    (a 2xx-3xx final status), optionally also require (mode="contains") or forbid
    (mode="not_contains") a substring in the response body. A failed keyword condition flips
    is_up to False with its own distinctly-prefixed error — see _check_keyword_match — instead
    of being conflated with a connection failure. The API layer rejects an explicit
    method="HEAD" combined with a keyword_match at creation/update time; the case above (method
    left unset) is handled here instead, since "unset" isn't itself invalid — it just needs to
    mean GET, not HEAD, once a keyword_match is in play.

    `dns_ms` is the timing of the caller's up-front is_url_blocked(url) check (see main.py) —
    passed in so it isn't measured twice, and used unless a redirect hop replaces it with its
    own (more specific) resolution timing.

    Return dict: checked_at, status_code, latency_ms, is_up, error, dns_ms, tcp_ms, tls_ms,
    ttfb_ms, tls_cert_expires_at, tls_cert_issuer.
    """
    checked_at = datetime.now(timezone.utc)
    result = {
        "checked_at": checked_at,
        "status_code": None,
        "latency_ms": None,
        "is_up": False,
        "error": None,
        "dns_ms": dns_ms,
        "tcp_ms": None,
        "tls_ms": None,
        "ttfb_ms": None,
        "tls_cert_expires_at": None,
        "tls_cert_issuer": None,
    }
    try:
        start = time.perf_counter()
        if method is not None or keyword_match:
            hop = await _follow_with_ssrf_check(client, method or "GET", url, dns_ms, headers=headers, auth=auth)
        else:
            try:
                hop = await _follow_with_ssrf_check(client, "HEAD", url, dns_ms, headers=headers, auth=auth)
                if hop.response.status_code >= 400:
                    hop = await _follow_with_ssrf_check(client, "GET", url, dns_ms, headers=headers, auth=auth)
            except (httpx.HTTPError, OSError):
                hop = await _follow_with_ssrf_check(client, "GET", url, dns_ms, headers=headers, auth=auth)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        is_up = 200 <= hop.response.status_code < 400
        error = None
        if is_up and keyword_match:
            error = _check_keyword_match(hop.response.text, keyword_match, keyword_match_mode)
            if error is not None:
                is_up = False
        result.update(
            status_code=hop.response.status_code,
            latency_ms=elapsed_ms,
            is_up=is_up,
            error=error,
            dns_ms=hop.dns_ms,
            tcp_ms=hop.tcp_ms,
            tls_ms=hop.tls_ms,
            ttfb_ms=hop.ttfb_ms,
            tls_cert_expires_at=hop.tls_cert_expires_at,
            tls_cert_issuer=hop.tls_cert_issuer,
        )
    except RedirectValidationError as e:
        result["error"] = str(e)
    except httpx.HTTPError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result
