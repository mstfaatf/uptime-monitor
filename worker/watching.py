"""Asks the backend whether anyone is currently using the site (GET /internal/watching).

The answer decides the worker's mode (see scheduler.py). Every failure, of any kind, reads as
"nobody is watching": a missing BACKEND_URL or INTERNAL_API_SECRET, a timeout, a connection
error, a non-200 response, or a body that isn't {"watching": <bool>}. The safe default is the
slow, database-friendly idle mode, never continuous checking.

Failures are logged as a warning at most once per WARNING_INTERVAL_SECONDS, so a backend that's
down for an hour produces a handful of lines, not one every poll. The secret is only ever put in
the request header, never in a log message.
"""

import logging
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

WATCHING_PATH = "/internal/watching"
SECRET_HEADER = "X-Internal-Secret"
WATCHING_TIMEOUT_SECONDS = 3
WARNING_INTERVAL_SECONDS = 60


class WatchingProbe:
    """Callable that returns True only on a well-formed {"watching": true} from the backend."""

    def __init__(
        self,
        backend_url: str | None,
        secret: str | None,
        client: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._url = f"{backend_url.rstrip('/')}{WATCHING_PATH}" if backend_url else None
        self._secret = secret or None
        self._client = client
        self._clock = clock
        self._last_warning_at: float | None = None

    def _warn(self, message: str, *args) -> None:
        now = self._clock()
        if self._last_warning_at is not None and now - self._last_warning_at < WARNING_INTERVAL_SECONDS:
            return
        self._last_warning_at = now
        logger.warning("Treating the site as unwatched (idle mode): " + message, *args)

    async def __call__(self) -> bool:
        if self._url is None or self._secret is None:
            self._warn("BACKEND_URL or INTERNAL_API_SECRET is not set")
            return False
        try:
            response = await self._client.get(
                self._url, headers={SECRET_HEADER: self._secret}, timeout=WATCHING_TIMEOUT_SECONDS
            )
        except httpx.TimeoutException:
            self._warn("%s timed out after %ss", self._url, WATCHING_TIMEOUT_SECONDS)
            return False
        except Exception as exc:  # connection refused, DNS failure, TLS error, anything else
            self._warn("%s failed: %s", self._url, type(exc).__name__)
            return False
        if response.status_code != 200:
            self._warn("%s returned HTTP %s", self._url, response.status_code)
            return False
        try:
            value = response.json()["watching"]
        except Exception:
            self._warn("%s returned an unreadable body", self._url)
            return False
        if not isinstance(value, bool):
            self._warn("%s returned a non-boolean 'watching' value", self._url)
            return False
        return value
