"""Resend client — a single send_email() wrapper, deliberately thin (no retry/queue logic).

RESEND_API_KEY is optional (see config.py): when unset, send_email() logs and returns False
rather than raising, so the app boots and every other feature works without a real Resend
account — a missing key is a safe degraded state (no email sent), not a startup failure like
a missing JWT_SECRET. A send that fails against a real Resend API (bad key, rate limit,
network error) is likewise logged and swallowed, not raised: email is always a side effect of
some other action (a check landing, a password-reset request) that should never itself fail
just because an email couldn't be sent.
"""

import logging

import resend

from config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via Resend. Returns True if it was actually sent, False if
    skipped (no API key configured) or if sending failed."""
    if not settings.RESEND_API_KEY:
        logger.info("RESEND_API_KEY not set, skipping email to %s: %s", to, subject)
        return False

    resend.api_key = settings.RESEND_API_KEY
    try:
        await resend.Emails.send_async(
            {
                "from": settings.RESEND_FROM_EMAIL,
                "to": [to],
                "subject": subject,
                "text": body,
            }
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s: %s", to, subject)
        return False
