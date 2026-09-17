"""Webhook payload construction and delivery (Phase 6, prompt 6.6).

send_webhook() is deliberately thin — one attempt, a short timeout, log-and-swallow on
failure — mirroring mail/client.py's send_email() philosophy exactly: a webhook send is always
a side effect of some other action (a check landing) that should never itself fail or block
that action. It never raises, so a webhook failure structurally can't corrupt or block the
SSE-push half of backend/realtime.py's notification handler, the same guarantee send_email()
already provides there.

SSRF: re-validated immediately before every send (not just at webhook creation in
routers/webhooks.py) — a URL can resolve to a safe address at creation time and an unsafe one
later (DNS rebinding), the same threat model worker/checker.py already defends against for
monitored target URLs on every check, not just at creation. Wrapped in asyncio.to_thread()
since is_url_blocked() does a blocking socket.getaddrinfo() call, and this runs inside
realtime.py's single shared event loop — blocking it here would delay every other concurrent
request/SSE stream the backend is serving, not just this one webhook send.

No redirect-following: httpx.AsyncClient(follow_redirects=False) — a 3xx response is simply
treated as a failed delivery, not chased. Unlike worker/checker.py's manual per-hop SSRF
revalidation loop for monitored target URLs (built because those URLs are checked routinely
and redirects are common and legitimate there), a webhook receiver essentially never needs to
legitimately redirect, so reimplementing that same revalidation machinery here isn't worth it.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from models import Check, Target
from security.ssrf import is_url_blocked

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5
SIGNATURE_HEADER = "X-Uptime-Monitor-Signature"


def build_webhook_payload(event: str, target: Target, region: str, check: Check, detail_url: str) -> dict:
    """Build the JSON payload sent to a webhook. `event` is one of "target.down", "target.up",
    "target.cert_expiring". `cert` is null unless this check captured TLS cert data (https://
    targets only) — same optional shape LatestCheckResponse already exposes it in, just
    reduced to the fields a webhook receiver actually needs to act on."""
    cert = None
    if check.tls_cert_expires_at is not None:
        cert = {
            "expires_at": check.tls_cert_expires_at.isoformat(),
            "days_remaining": (check.tls_cert_expires_at - datetime.now(timezone.utc)).days,
            "issuer": check.tls_cert_issuer,
        }
    return {
        "event": event,
        "target": {"id": target.id, "name": target.name, "url": target.url},
        "region": region,
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
        "error": check.error,
        "cert": cert,
        "detail_url": detail_url,
    }


def _sign(secret: str, raw_body: bytes) -> str:
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def send_webhook(url: str, secret: str, payload: dict) -> bool:
    """POST payload as JSON to url, signed via SIGNATURE_HEADER. Returns True only if the
    request was actually sent and got back a 2xx response; False for an SSRF-blocked
    destination, a timeout/connection error, or any non-2xx response (redirects included —
    follow_redirects=False means a 3xx is returned to us directly, not followed, and fails the
    2xx check the same as any other non-success status)."""
    blocked, reason = await asyncio.to_thread(is_url_blocked, url)
    if blocked:
        logger.warning("Webhook delivery to %s blocked at send time: %s", url, reason)
        return False

    raw_body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: _sign(secret, raw_body)}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=raw_body, headers=headers)
        if not response.is_success:
            logger.warning("Webhook delivery to %s failed: HTTP %s", url, response.status_code)
            return False
        return True
    except Exception:
        logger.exception("Webhook delivery to %s failed", url)
        return False
