"""API-key authentication (Phase 6, prompt 6.7): a Bearer-token alternative to the cookie
session, usable only on a specific, explicitly-scoped set of endpoints — each opts in via
Depends(get_current_user_or_api_key(scope)); every endpoint still using the plain
Depends(get_current_user) is completely untouched by this module and stays cookie-only.

Never used by routers/api_keys.py itself, at any scope: a key must never be able to manage
other keys (mint or revoke them), so that router's own endpoints depend on the plain
get_current_user directly, not this factory.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from database import get_db
from models import ApiKey, User

# 'full' is a strict superset of 'read' — a full-scope key can do everything a read-scope key
# can, plus the write operations each route declares via get_current_user_or_api_key("full").
SCOPE_LEVELS = {"read": 1, "full": 2}

# How long a key's last_used_at is trusted before it's worth updating again. Throttled, not
# bumped on literally every authenticated request — that would be a real, needless write on
# every single API call. "Used within the last hour" is precise enough for the actual purpose
# (helping a user notice/revoke a leaked, currently-active key), not a precise audit log.
LAST_USED_UPDATE_INTERVAL = timedelta(hours=1)


def hash_api_key(raw_key: str) -> str:
    """SHA-256, not argon2 — same reasoning as PasswordResetToken.token_hash: a 32-byte
    cryptographically random value has no dictionary to defend against, so a fast hash is
    correct here (argon2 would just make every request's key lookup needlessly slow)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def _resolve_api_key(session: AsyncSession, raw_key: str) -> tuple[User, ApiKey] | None:
    """Returns (user, api_key) for a valid, unrevoked key whose owning user still exists; None
    for an unknown, revoked, or otherwise unresolvable key."""
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
    api_key = result.scalar_one_or_none()
    if api_key is None or api_key.revoked_at is not None:
        return None
    user_result = await session.execute(select(User).where(User.id == api_key.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None
    return user, api_key


def _touch_last_used(api_key: ApiKey) -> None:
    now = datetime.now(timezone.utc)
    if api_key.last_used_at is None or (now - api_key.last_used_at) > LAST_USED_UPDATE_INTERVAL:
        api_key.last_used_at = now


def get_current_user_or_api_key(scope: str = "read"):
    """Dependency factory used on the specific endpoints that accept API-key auth.

    `Authorization: Bearer <key>` present -> must resolve to a valid, unrevoked key whose own
    scope is sufficient for `scope` required here (401 if the key itself is invalid/unknown/
    revoked, 403 if it's valid but under-scoped) — deliberately NO silent fallback to cookie
    auth in that case. A caller that explicitly presented a key deserves an honest answer about
    that key, not a session it never offered; silently trying a cookie behind its back would be
    surprising and could mask a real integration bug.

    `Authorization` header absent entirely -> defers completely to the existing, unmodified
    get_current_user (cookie-only). This is what keeps every current cookie-authenticated
    caller of these same endpoints (the dashboard) working exactly as before — this factory
    never changes get_current_user itself, only adds an alternative path in front of it.

    On success via a key, stamps request.state.api_key — read downstream by
    rate_limit.py's api_key_or_remote_address (keys the new per-key rate limit) and by
    routers/targets.py's GET /targets/{id}/checks (gates cursor pagination to key-authenticated
    requests only).
    """

    async def dependency(request: Request, session: AsyncSession = Depends(get_db)) -> User:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            raw_key = auth_header[len("Bearer "):].strip()
            resolved = await _resolve_api_key(session, raw_key) if raw_key else None
            if resolved is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
            user, api_key = resolved
            if SCOPE_LEVELS[api_key.scope] < SCOPE_LEVELS[scope]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"This API key's scope ('{api_key.scope}') does not permit this operation "
                    f"(requires '{scope}')",
                )
            _touch_last_used(api_key)
            request.state.api_key = api_key
            return user
        return await get_current_user(request, session)

    return dependency
