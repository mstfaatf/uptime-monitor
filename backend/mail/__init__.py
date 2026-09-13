"""Transactional email: a single send_email() wrapper around Resend, plus plain-text
templates, shared by downtime/cert-expiry alerting and password reset (Phase 4).

Named "mail", not "email": a package literally named "email" at backend/'s root would shadow
Python's stdlib email module for the whole app (backend/ sits directly on sys.path, the same
way config.py/database.py/etc. are already imported unqualified) — and starlette.responses,
fastapi.routing, and uvicorn.server all import the stdlib email module directly, so that
would have broken core request handling, not just this feature. Verified in the running api
container before naming this: `python -c "import email; print(email.__file__)"` resolves to
the stdlib module, and grepping site-packages for `import email` turns up starlette/fastapi/
uvicorn as real, active importers.
"""

from mail.client import send_email
from mail.templates import cert_expiry_alert_email, downtime_alert_email, password_reset_email

__all__ = [
    "send_email",
    "downtime_alert_email",
    "cert_expiry_alert_email",
    "password_reset_email",
]
