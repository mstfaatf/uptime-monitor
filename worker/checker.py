"""Perform a single HTTP check: HEAD first, retry once with GET if HEAD fails or status >= 400."""

import asyncio
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

from ssrf import is_url_blocked

MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)


class RedirectValidationError(Exception):
    """Raised when a redirect chain can't be safely followed (SSRF-blocked hop, or too many hops)."""


async def _follow_with_ssrf_check(client: httpx.AsyncClient, method: str, url: str) -> httpx.Response:
    """
    Perform `method` against `url`, following redirects manually (follow_redirects=False) so
    each hop's target can be re-validated against the SSRF blocklist before it's followed.
    follow_redirects=True would follow a redirect to a blocked address without ever re-checking
    it — a target can pass the SSRF check at creation/check time but 3xx-redirect to e.g.
    http://169.254.169.254/ or http://127.0.0.1/, bypassing the guard entirely.
    """
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        resp = await client.request(method, current_url, follow_redirects=False)
        if resp.status_code in _REDIRECT_STATUS_CODES and "Location" in resp.headers:
            next_url = urljoin(current_url, resp.headers["Location"])
            # is_url_blocked() does a blocking socket.getaddrinfo() call — run it off the event
            # loop so one redirect-hop resolution doesn't stall every other in-flight check.
            blocked, reason = await asyncio.to_thread(is_url_blocked, next_url)
            if blocked:
                raise RedirectValidationError(f"Redirect target blocked: {reason}")
            current_url = next_url
            continue
        return resp
    raise RedirectValidationError(f"Too many redirects (>{MAX_REDIRECTS})")


async def check_url(client: httpx.AsyncClient, url: str) -> dict:
    """
    Attempt HEAD first; if HEAD fails or returns >= 400, retry once with GET.
    Record latency_ms and status_code from the successful attempt.
    Return dict: checked_at, status_code (int|None), latency_ms (int|None), is_up (bool), error (str|None).
    """
    checked_at = datetime.now(timezone.utc)
    result = {
        "checked_at": checked_at,
        "status_code": None,
        "latency_ms": None,
        "is_up": False,
        "error": None,
    }
    try:
        start = time.perf_counter()
        try:
            resp = await _follow_with_ssrf_check(client, "HEAD", url)
            if resp.status_code >= 400:
                resp = await _follow_with_ssrf_check(client, "GET", url)
        except (httpx.HTTPError, OSError):
            resp = await _follow_with_ssrf_check(client, "GET", url)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result["status_code"] = resp.status_code
        result["latency_ms"] = elapsed_ms
        result["is_up"] = 200 <= resp.status_code < 400
    except RedirectValidationError as e:
        result["error"] = str(e)
    except httpx.HTTPError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result
