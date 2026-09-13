"""Target endpoints with strict ownership enforcement."""

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import realtime
from auth import get_current_user
from database import get_db
from models import Check, Target, TargetRegionSchedule, User
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
    # How many consecutive failures this (target, region) is currently on, per
    # target_region_schedule — resets to 0 the moment a check succeeds (see
    # worker/main.py's reschedule_target), so this is only ever non-zero on a check that
    # itself failed. Null when there's no schedule row yet for this region (e.g. a
    # historical CheckHistoryEntry, where a "live schedule state" reading doesn't apply to a
    # past check) rather than a live latest-check reading. Used to debounce the down/degraded
    # classification — see lib/thresholds.ts's CONSECUTIVE_FAILURES_DOWN_THRESHOLD.
    consecutive_failures: int | None = None


class TargetStatusResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str
    # Keyed by region (see backend/alembic/versions/006_add_region_and_target_schedule.py),
    # not a single latest_check — a target's reachability/latency is now tracked per checking
    # region and each region's most recent result is reported independently. Deliberately no
    # derived "overall status" field: collapsing multiple regions into one boolean would hide
    # exactly the per-region signal this exists to show (see the Phase 2 design report). A
    # target with no checks yet in any region reports an empty dict, not null.
    latest_checks: dict[str, LatestCheckResponse]


class CheckHistoryEntry(LatestCheckResponse):
    # Same shape as one region's entry in TargetStatusResponse.latest_checks, plus which
    # region it's from — needed here because GET /targets/{id}/checks returns a flat list
    # for one region rather than a region-keyed dict.
    region: str


def _check_to_response_dict(check: Check, consecutive_failures: int | None = None) -> dict:
    """Build the LatestCheckResponse-shaped dict for one check row. consecutive_failures is a
    separate, optional argument (not read off `check`) because it comes from
    target_region_schedule, a different table keyed by (target_id, region) — it's only ever
    supplied for a *latest* check (see build_target_status_payload), never for a historical
    CheckHistoryEntry, where a live schedule-state reading doesn't correspond to that past
    check."""
    days_remaining = None
    if check.tls_cert_expires_at is not None:
        days_remaining = (check.tls_cert_expires_at - datetime.now(timezone.utc)).days
    return {
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
        "consecutive_failures": consecutive_failures,
    }


def build_target_status_payload(
    target: Target,
    checks_by_region: dict[str, Check],
    failures_by_region: dict[str, int] | None = None,
) -> dict:
    """Build the same {target + latest_checks} shape used by GET /targets/status, for reuse by
    the SSE push in realtime.py — one place decides what a "target status" looks like, so the
    two delivery paths (poll and push) can never silently drift apart. checks_by_region holds
    each region's single most recent check for this target (empty if none yet in any region);
    failures_by_region holds that region's current target_region_schedule.consecutive_failures
    (missing/None if no schedule row exists yet for that region)."""
    failures_by_region = failures_by_region or {}
    return {
        "id": target.id,
        "url": target.url,
        "name": target.name,
        "created_at": target.created_at.isoformat(),
        "latest_checks": {
            region: _check_to_response_dict(check, failures_by_region.get(region))
            for region, check in checks_by_region.items()
        },
    }


def _latest_checks_per_region_query(user_id: int | None = None, target_id: int | None = None):
    """Shared query shape for "target(s) + each region's latest check (+ that region's current
    consecutive_failures)": used by both the /status list endpoint (filtered by user_id) and
    realtime's single-target lookup (filtered by target_id). Returns one
    (Target, Check, consecutive_failures) row per (target, region) that has at least one check,
    plus one (Target, None, None) row for a target with no checks in any region yet — a target
    is never dropped just because it (or one region) has no data.

    target_region_schedule is joined on (target_id, region) taken from the ranked Check
    subquery, not from a fixed column of Target — a target's region set is only known from
    whichever regions it actually has checks in. consecutive_failures is None whenever no
    schedule row exists yet for that (target, region), e.g. immediately after target creation,
    before any worker has picked it up."""
    ranked = (
        select(
            Check,
            func.row_number()
            .over(partition_by=(Check.target_id, Check.region), order_by=Check.checked_at.desc())
            .label("rn"),
        )
    ).subquery()
    latest_check = aliased(Check, ranked)

    stmt = (
        select(Target, latest_check, TargetRegionSchedule.consecutive_failures)
        .select_from(Target)
        .outerjoin(ranked, (ranked.c.target_id == Target.id) & (ranked.c.rn == 1))
        .outerjoin(
            TargetRegionSchedule,
            (TargetRegionSchedule.target_id == ranked.c.target_id)
            & (TargetRegionSchedule.region == ranked.c.region),
        )
    )
    if user_id is not None:
        stmt = stmt.where(Target.user_id == user_id).order_by(Target.created_at.desc())
    if target_id is not None:
        stmt = stmt.where(Target.id == target_id)
    return stmt


def _group_checks_by_target(
    rows,
) -> tuple[dict[int, Target], dict[int, dict[str, Check]], dict[int, dict[str, int]]]:
    """Collapse the (Target, Check|None, consecutive_failures|None) rows from
    _latest_checks_per_region_query — one row per (target, region) — into per-target Target
    objects, {region: Check} dicts, and {region: consecutive_failures} dicts, preserving the
    order targets first appeared in (the query's own ORDER BY, when applied)."""
    targets_by_id: dict[int, Target] = {}
    checks_by_target: dict[int, dict[str, Check]] = {}
    failures_by_target: dict[int, dict[str, int]] = {}
    for target, check, consecutive_failures in rows:
        if target.id not in targets_by_id:
            targets_by_id[target.id] = target
            checks_by_target[target.id] = {}
            failures_by_target[target.id] = {}
        if check is not None:
            checks_by_target[target.id][check.region] = check
            if consecutive_failures is not None:
                failures_by_target[target.id][check.region] = consecutive_failures
    return targets_by_id, checks_by_target, failures_by_target


@router.get("/status", response_model=list[TargetStatusResponse])
async def list_targets_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return each target owned by the user with its latest check per region (one target per
    id, no duplicates; each region's own most recent result reported independently)."""
    result = await db.execute(_latest_checks_per_region_query(user_id=current_user.id))
    targets_by_id, checks_by_target, failures_by_target = _group_checks_by_target(result.all())
    return [
        TargetStatusResponse(
            **build_target_status_payload(target, checks_by_target[target_id], failures_by_target[target_id])
        )
        for target_id, target in targets_by_id.items()
    ]


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


@router.get("/{target_id}", response_model=TargetStatusResponse)
async def get_target_detail(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one target with its latest check per region — the same shape as one row of
    GET /targets/status, built via the same query/payload helpers so the two can never drift
    apart. 404 (not 403) for a target that doesn't exist or isn't owned by the caller — same
    "can't tell the difference" pattern as DELETE below."""
    result = await db.execute(_latest_checks_per_region_query(target_id=target_id))
    rows = result.all()
    if not rows or rows[0][0].user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    targets_by_id, checks_by_target, failures_by_target = _group_checks_by_target(rows)
    target = targets_by_id[target_id]
    return TargetStatusResponse(
        **build_target_status_payload(target, checks_by_target[target_id], failures_by_target[target_id])
    )


@router.get("/{target_id}/checks", response_model=list[CheckHistoryEntry])
async def get_target_checks(
    target_id: int,
    region: str,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return this target's check history for one region, oldest first — the raw material for
    the detail page's latency chart/heatmap/incident timeline. `region` is required rather
    than defaulting to "every region mixed together": every analytics view on the detail page
    is per-region by design (see the Phase 2 report's independent-display decision), so there
    is no meaningful combined history to return. 404 (not 403) if the target doesn't exist or
    isn't owned by the caller."""
    limit = max(1, min(limit, 2000))
    owns = await db.execute(
        select(Target.id).where(Target.id == target_id, Target.user_id == current_user.id)
    )
    if owns.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    result = await db.execute(
        select(Check)
        .where(Check.target_id == target_id, Check.region == region)
        .order_by(Check.checked_at.asc())
        .limit(limit)
    )
    checks = result.scalars().all()
    return [CheckHistoryEntry(**_check_to_response_dict(check), region=check.region) for check in checks]


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
