"""Shared slowapi Limiter instance, plus the per-API-key rate-limit key function (Phase 6,
prompt 6.7).

Lives in its own module (not main.py) so routers can import it and decorate endpoints
without a circular import (main.py imports the routers; the routers would otherwise need
to import back from main.py).

The Limiter's own default key_func is client IP (slowapi's get_remote_address), the same way
for every existing IP-keyed limit in this app — including POST /targets, which is per-user in
principle but per-IP in practice here: keying by user would mean re-decoding the session
cookie inside the rate limiter's key function (slowapi's key_func only ever sees the raw
Request, before FastAPI dependencies like get_current_user run), which duplicates auth logic
for little real benefit — an attacker hammering this endpoint from one IP is caught either
way. Every existing @limiter.limit(...) call (no key_func argument) keeps using this default,
completely untouched by the addition below.

In-memory, per-process storage (slowapi's default): correct for a single backend instance,
which is the current and near-term deployment plan. If the backend is ever horizontally
scaled to multiple instances, each process would enforce its own separate limit — this needs
a shared store (e.g. Redis, via slowapi's storage_uri) before that happens. This applies
equally to the new per-key limit below, not just the existing IP-keyed ones.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)


def api_key_or_remote_address(request: Request) -> str:
    """Rate-limit key for API-key-eligible routes: the API key's own id if this request is
    API-key-authenticated (request.state.api_key, stamped by
    auth.api_key.get_current_user_or_api_key when a Bearer key resolves), else the client's
    IP — the same fallback get_remote_address already provides for every other limit in this
    app. Reading request.state here doesn't duplicate any auth logic (unlike the user-keying
    POST /targets considered and rejected above) — it just reads state a FastAPI dependency
    already computed before this key_func runs, since dependency injection resolves before the
    route (and its slowapi decorator) is invoked.

    Gives programmatic API-key traffic its own, more generous per-key quota, independent of
    whatever else might share that key owner's IP (e.g. a household NAT), without touching any
    existing IP-keyed limit — a cookie-authenticated request to the same route still falls back
    to IP-keying here, exactly like every other unauthenticated-by-key endpoint.
    """
    api_key = getattr(request.state, "api_key", None)
    if api_key is not None:
        return f"api_key:{api_key.id}"
    return get_remote_address(request)


# Per-key limit applied to every API-key-eligible route (Phase 6, prompt 6.7) — see
# routers/targets.py and routers/webhooks.py for exactly which endpoints carry it. 60/minute:
# generous enough that a real programmatic integration (a Prometheus exporter, a personal
# dashboard polling every few seconds) comfortably fits underneath it, well above anything a
# human clicking through the web dashboard would ever hit on these specific routes, while still
# bounding a misconfigured or abusive integration. Not applied to POST /api-keys or
# POST /webhooks themselves — those are cookie-only endpoints (see auth/api_key.py's module
# docstring: a key can never manage other keys, and POST /webhooks is key-eligible for scope
# 'full' but still gets its own separate, IP-keyed creation limit below, matching
# POST /targets's existing pattern).
API_KEY_RATE_LIMIT = "60/minute"
