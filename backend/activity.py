"""In-memory record of recent signed-in activity, read by GET /internal/watching.

The workers ask that endpoint whether anyone is using the site, to decide between checking
everything on a slow, database-friendly schedule and checking continuously. "Someone is using
it" means an open SSE stream (realtime.py tracks those) or a request whose session cookie
resolved to a real user within the last WATCHING_WINDOW_SECONDS. This module holds the second
half: a single timestamp, nothing about who the user was.

Only cookie-authenticated requests are recorded, from auth.deps._user_from_session_cookie, the
one place a session cookie is turned into a user. API-key requests never reach that function
(auth.api_key resolves the key itself and returns before falling back to the cookie path), so a
script polling the API can't hold the workers in continuous mode. Login, registration, and any
request that fails authentication never record anything either.

Single-process assumption: like slowapi's in-memory rate limits (rate_limit.py) and
realtime.py's in-memory subscriber registry, this lives in the API process's own memory. The
deployment runs exactly one API process; with several, each would only know about its own
traffic, and the endpoint would need a shared store instead.
"""

import time

from config import settings

# Indirection so tests can move time forward without patching time.monotonic itself, which the
# event loop also relies on.
_clock = time.monotonic

_last_cookie_activity: float | None = None


def record_cookie_activity() -> None:
    """Mark that a cookie-authenticated request just resolved to a real user."""
    global _last_cookie_activity
    _last_cookie_activity = _clock()


def recently_active() -> bool:
    """True if a cookie-authenticated request happened within WATCHING_WINDOW_SECONDS."""
    if _last_cookie_activity is None:
        return False
    return _clock() - _last_cookie_activity < settings.WATCHING_WINDOW_SECONDS


def reset() -> None:
    """Forget all recorded activity. Used by tests."""
    global _last_cookie_activity
    _last_cookie_activity = None
