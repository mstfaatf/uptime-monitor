"""Webhook CRUD endpoints (Phase 6, prompt 6.6). Ownership enforced identically to every other
user-owned resource in this app (CLAUDE.md rule 1) — every query here filters by
Webhook.user_id == current_user.id. POST/GET/DELETE only, no PATCH — matches the precedent
already set by routers/tags.py's own CRUD shape; a webhook's toggles are fixed at creation for
now, revisit if editing them without delete-and-recreate turns out to matter.

Webhook URLs are validated against the same SSRF blocklist used for target URLs
(backend/security/ssrf.py) here, at creation — the same "fast feedback" principle as
POST /targets — AND re-validated immediately before every send (see backend/webhooks.py's
send_webhook), since a URL can resolve safely at creation and unsafely later (DNS rebinding).

All three endpoints are API-key-eligible at scope 'full' (Phase 6, prompt 6.7) — "manage
webhooks" is a full-scope-only capability, not covered by 'read' at all (see auth/api_key.py).
POST also carries a dedicated 10/minute IP-keyed creation limit, mirroring POST /targets'
existing pattern, on top of the per-key limit every key-eligible route gets.
"""

import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user_or_api_key
from database import get_db
from models import User, Webhook
from rate_limit import API_KEY_RATE_LIMIT, api_key_or_remote_address, limiter
from security.ssrf import is_url_blocked

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_full_or_key = Depends(get_current_user_or_api_key("full"))


def _validate_webhook_url(url: str) -> None:
    """Raises HTTPException(400) if the URL isn't a well-formed http(s) URL, or resolves to a
    blocked (SSRF) range. Mirrors POST /targets' own creation-time validation shape/error
    style in routers/targets.py."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook url must be a valid http or https URL",
        )
    blocked, reason = is_url_blocked(url)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This webhook URL cannot be used: {reason}",
        )


class WebhookCreate(BaseModel):
    url: str
    alert_on_downtime: bool = True
    alert_on_cert_expiry: bool = True


class WebhookResponse(BaseModel):
    id: int
    url: str
    alert_on_downtime: bool
    alert_on_cert_expiry: bool
    enabled: bool
    created_at: str

    class Config:
        from_attributes = True


class WebhookCreatedResponse(WebhookResponse):
    # Shown exactly once, in the create response — never returned by GET /webhooks or anywhere
    # else. The receiver needs it to verify X-Uptime-Monitor-Signature; there's no legitimate
    # reason for this app to hand it back out later. Same "shown once" convention a generated
    # API key or a password-reset link's raw token would follow.
    secret: str


def _webhook_to_response(webhook: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=webhook.id,
        url=webhook.url,
        alert_on_downtime=webhook.alert_on_downtime,
        alert_on_cert_expiry=webhook.alert_on_cert_expiry,
        enabled=webhook.enabled,
        created_at=webhook.created_at.isoformat(),
    )


@router.get("", response_model=list[WebhookResponse])
@limiter.limit(API_KEY_RATE_LIMIT, key_func=api_key_or_remote_address)
async def list_webhooks(
    request: Request,
    current_user: User = _full_or_key,
    db: AsyncSession = Depends(get_db),
):
    """Return all webhooks owned by the authenticated user. Never includes `secret`."""
    result = await db.execute(
        select(Webhook).where(Webhook.user_id == current_user.id).order_by(Webhook.created_at.desc())
    )
    return [_webhook_to_response(w) for w in result.scalars().all()]


@router.post("", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
@limiter.limit(API_KEY_RATE_LIMIT, key_func=api_key_or_remote_address)
async def create_webhook(
    request: Request,
    body: WebhookCreate,
    current_user: User = _full_or_key,
    db: AsyncSession = Depends(get_db),
):
    """Create a new webhook. `secret` is always server-generated (never user-supplied) via
    secrets.token_urlsafe — a random 32-byte value, the same generation approach already used
    for password-reset tokens, with no dictionary to defend against so no reason for a
    user-chosen value here."""
    url = body.url.strip()
    _validate_webhook_url(url)

    webhook = Webhook(
        user_id=current_user.id,
        url=url,
        secret=secrets.token_urlsafe(32),
        alert_on_downtime=body.alert_on_downtime,
        alert_on_cert_expiry=body.alert_on_cert_expiry,
    )
    db.add(webhook)
    await db.flush()
    await db.refresh(webhook)
    return WebhookCreatedResponse(**_webhook_to_response(webhook).model_dump(), secret=webhook.secret)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(API_KEY_RATE_LIMIT, key_func=api_key_or_remote_address)
async def delete_webhook(
    request: Request,
    webhook_id: int,
    current_user: User = _full_or_key,
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook only if it belongs to the authenticated user. 404 (not 403) if it
    doesn't exist or isn't owned by the caller, same pattern as every other ownership-scoped
    endpoint."""
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == current_user.id))
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await db.delete(webhook)
    return None
