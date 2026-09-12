"""Shared slowapi Limiter instance.

Lives in its own module (not main.py) so routers can import it and decorate endpoints
without a circular import (main.py imports the routers; the routers would otherwise need
to import back from main.py).

Keyed by client IP (slowapi's get_remote_address), the same way for every limited endpoint
below — including POST /targets, which is per-user in principle but per-IP in practice here:
keying by user would mean re-decoding the session cookie inside the rate limiter's key
function (slowapi's key_func only ever sees the raw Request, before FastAPI dependencies like
get_current_user run), which duplicates auth logic for little real benefit — an attacker
hammering this endpoint from one IP is caught either way.

In-memory, per-process storage (slowapi's default): correct for a single backend instance,
which is the current and near-term deployment plan. If the backend is ever horizontally
scaled to multiple instances, each process would enforce its own separate limit — this needs
a shared store (e.g. Redis, via slowapi's storage_uri) before that happens.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
