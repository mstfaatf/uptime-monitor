"""API key CRUD endpoints (Phase 6, prompt 6.7).

Cookie-auth ONLY — every endpoint here depends on the plain get_current_user, never
get_current_user_or_api_key, at any scope: a key must never be usable to mint or revoke other
keys, regardless of its own scope (see auth/api_key.py's module docstring). Ownership enforced
identically to every other user-owned resource in this app (CLAUDE.md rule 1).
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from auth.api_key import SCOPE_LEVELS, hash_api_key
from database import get_db
from models import ApiKey, User
from rate_limit import limiter

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

# "um_" (uptime monitor) prefix + a 32-byte URL-safe random suffix — the prefix alone makes a
# leaked key grep-able/recognizable in logs; the random part is what actually matters
# cryptographically. Same secrets.token_urlsafe(32) generation already used for password-reset
# tokens (see routers/auth.py), just with a recognizable prefix prepended.
KEY_PREFIX_TAG = "um_"
KEY_PREFIX_DISPLAY_LENGTH = 12


class ApiKeyCreate(BaseModel):
    name: str
    scope: str = "read"


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scope: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None

    class Config:
        from_attributes = True


class ApiKeyCreatedResponse(ApiKeyResponse):
    # Shown exactly once, in the create response — never returned by GET /api-keys or anywhere
    # else. The raw key is never stored at all (only its hash), so no later endpoint could
    # return it again even if we wanted to.
    key: str


def _api_key_to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scope=api_key.scope,
        created_at=api_key.created_at.isoformat(),
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        revoked_at=api_key.revoked_at.isoformat() if api_key.revoked_at else None,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all API keys owned by the authenticated user, including revoked ones (with their
    revoked_at populated) — an audit trail of what existed and when it stopped working, not
    just currently-active keys. Never includes the hash or the raw key."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == current_user.id).order_by(ApiKey.created_at.desc())
    )
    return [_api_key_to_response(k) for k in result.scalars().all()]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The raw key is generated here, shown in this one response, and
    never stored or retrievable again — only its SHA-256 hash is persisted (see
    auth/api_key.py's hash_api_key)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Key name cannot be empty")
    if body.scope not in SCOPE_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"scope must be one of {sorted(SCOPE_LEVELS)}",
        )

    raw_key = KEY_PREFIX_TAG + secrets.token_urlsafe(32)
    api_key = ApiKey(
        user_id=current_user.id,
        name=name,
        key_prefix=raw_key[:KEY_PREFIX_DISPLAY_LENGTH],
        key_hash=hash_api_key(raw_key),
        scope=body.scope,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    return ApiKeyCreatedResponse(**_api_key_to_response(api_key).model_dump(), key=raw_key)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a key only if it belongs to the authenticated user — sets revoked_at rather than
    deleting the row (see models/api_key.py's docstring on the soft-delete shape). Idempotent:
    revoking an already-revoked key just leaves its original revoked_at untouched, no error.
    404 (not 403) if the key doesn't exist or isn't owned by the caller, same pattern as every
    other ownership-scoped endpoint."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.user_id == current_user.id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return None
