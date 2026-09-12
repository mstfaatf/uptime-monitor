"""Target endpoints with strict ownership enforcement."""

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import realtime
from auth import get_current_user
from database import get_db
from models import Check, Target, User
from rate_limit import limiter
from security.ssrf import is_url_blocked

router = APIRouter(prefix="/targets", tags=["targets"])

# How often the SSE stream sends a comment line if there's nothing new to report — keeps
# intermediate proxies/load balancers from timing out an idle connection, and gives the
# browser a steady heartbeat to notice a dead connection sooner than TCP's own timeouts would.
SSE_KEEPALIVE_SECONDS = 15


def normalize_url(url: str) -> str:
    """Trim whitespace, require http/https, normalize trailing slash (remove)."""
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    path = (parsed.path or "/").rstrip("/") or ""
    netloc = parsed.netloc or ""
    if parsed.port and (parsed.scheme == "https" and parsed.port != 443 or parsed.scheme == "http" and parsed.port != 80):
        netloc = f"{parsed.hostname}:{parsed.port}"
    elif parsed.hostname:
        netloc = parsed.hostname
    normalized = f"{parsed.scheme}://{netloc}{path}" if path else f"{parsed.scheme}://{netloc}"
    if parsed.query:
        normalized += "?" + parsed.query
    if parsed.fragment:
        normalized += "#" + parsed.fragment
    return normalized


class TargetCreate(BaseModel):
    url: HttpUrl
    name: str | None = None


class TargetResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str

    class Config:
        from_attributes = True


class LatestCheckResponse(BaseModel):
    checked_at: str | None
    is_up: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None
    # DNS/TCP/TLS/TTFB timing breakdown for this check. Any phase the check didn't reach
    # (e.g. no TLS on a plain http:// target, or a connect failure before DNS even resolved)
    # is null rather than 0 — don't render a null phase as "0ms."
    dns_ms: int | None
    tcp_ms: int | None
    tls_ms: int | None
    ttfb_ms: int | None
    # TLS cert info, https:// targets only (null otherwise). tls_cert_days_remaining is
    # derived here at read time from tls_cert_expires_at, not stored — see
    # backend/alembic/versions/004_add_checks_timing_and_cert_columns.py. Negative means
    # already expired; this is intentionally exposed as-is (Phase 2.5's alerting will decide
    # its own threshold), not clamped to zero.
    tls_cert_expires_at: str | None
    tls_cert_issuer: str | None
    tls_cert_days_remaining: int | None


class TargetStatusResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str
    latest_check: LatestCheckResponse | None


def build_target_status_payload(target: Target, check: Check | None) -> dict:
    """Build the same {target + latest_check} shape used by GET /targets/status, for reuse by
    the SSE push in realtime.py — one place decides what a "target status" looks like, so the
    two delivery paths (poll and push) can never silently drift apart."""
    latest_check = None
    if check:
        days_remaining = None
        if check.tls_cert_expires_at is not None:
            days_remaining = (check.tls_cert_expires_at - datetime.now(timezone.utc)).days
        latest_check = {
            "checked_at": check.checked_at.isoformat() if check.checked_at else None,
            "is_up": check.is_up,
            "status_code": check.status_code,
            "latency_ms": check.latency_ms,
            "error": check.error,
            "dns_ms": check.dns_ms,
            "tcp_ms": check.tcp_ms,
            "tls_ms": check.tls_ms,
            "ttfb_ms": check.ttfb_ms,
            "tls_cert_expires_at": check.tls_cert_expires_at.isoformat() if check.tls_cert_expires_at else None,
            "tls_cert_issuer": check.tls_cert_issuer,
            "tls_cert_days_remaining": days_remaining,
        }
    return {
        "id": target.id,
        "url": target.url,
        "name": target.name,
        "created_at": target.created_at.isoformat(),
        "latest_check": latest_check,
    }


def _latest_check_query(user_id: int | None = None, target_id: int | None = None):
    """Shared query shape for "target(s) + their latest check": used by both the /status list
    endpoint (filtered by user_id) and realtime's single-target lookup (filtered by target_id)."""
    latest_check_id = (
        select(Check.id)
        .where(Check.target_id == Target.id)
        .order_by(Check.checked_at.desc())
        .limit(1)
        .correlate(Target)
        .scalar_subquery()
    )
    stmt = select(Target, Check).select_from(Target).outerjoin(Check, Check.id == latest_check_id)
    if user_id is not None:
        stmt = stmt.where(Target.user_id == user_id).order_by(Target.created_at.desc())
    if target_id is not None:
        stmt = stmt.where(Target.id == target_id)
    return stmt


@router.get("/status", response_model=list[TargetStatusResponse])
async def list_targets_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return each target owned by the user with its latest check (one per target, no duplicates)."""
    result = await db.execute(_latest_check_query(user_id=current_user.id))
    rows = result.all()
    return [TargetStatusResponse(**build_target_status_payload(target, check)) for target, check in rows]


@router.get("/stream")
async def stream_target_updates(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events stream of check-result updates for the authenticated user's own
    targets only. The worker NOTIFYs after each check commits; realtime.py resolves the
    notified target_id to its owning user and forwards the event only to that user's queue(s)
    here — this endpoint never sees, and can never accidentally forward, another user's data.
    """
    queue = realtime.subscribe(current_user.id)

    async def event_generator():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            realtime.unsubscribe(current_user.id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx-style proxy buffering of the stream
        },
    )


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all targets owned by the authenticated user."""
    result = await db.execute(
        select(Target).where(Target.user_id == current_user.id).order_by(Target.created_at.desc())
    )
    targets = result.scalars().all()
    return [
        TargetResponse(id=t.id, url=t.url, name=t.name, created_at=t.created_at.isoformat())
        for t in targets
    ]


@router.post("", response_model=TargetResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_target(
    request: Request,
    body: TargetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new target. URL is normalized; duplicate normalized URL per user returns 409."""
    raw = str(body.url).strip()
    try:
        normalized = normalize_url(raw)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    blocked, reason = is_url_blocked(normalized)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This URL cannot be monitored: {reason}",
        )

    result = await db.execute(
        select(Target).where(
            Target.user_id == current_user.id,
            Target.normalized_url == normalized,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A target with this URL already exists.",
        )
    target = Target(
        user_id=current_user.id,
        url=raw,
        normalized_url=normalized,
        name=(body.name.strip() or None) if body.name else None,
    )
    db.add(target)
    await db.flush()
    await db.refresh(target)
    return TargetResponse(id=target.id, url=target.url, name=target.name, created_at=target.created_at.isoformat())


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a target only if it belongs to the authenticated user. Checks are removed (CASCADE)."""
    result = await db.execute(
        select(Target).where(Target.id == target_id, Target.user_id == current_user.id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    await db.delete(target)
    return None
