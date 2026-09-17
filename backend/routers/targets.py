"""Target endpoints with strict ownership enforcement."""

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

import realtime
from auth import get_current_user
from database import get_db
from export import build_csv
from models import Check, Tag, Target, TargetRegionSchedule, User
from rate_limit import limiter
from routers.tags import TagResponse, _tag_to_response
from security.crypto import encrypt_secret
from security.ssrf import is_url_blocked

router = APIRouter(prefix="/targets", tags=["targets"])

# Request customization (Phase 6, prompt 6.2). request_method=None preserves the worker's
# original HEAD-then-GET-on-failure default (see worker/checker.py) — only these three
# explicit choices are supported; an explicit method disables that fallback entirely, so it's
# deliberately kept small rather than opening up arbitrary HTTP verbs.
ALLOWED_REQUEST_METHODS = {"GET", "POST", "HEAD"}
ALLOWED_KEYWORD_MATCH_MODES = {"contains", "not_contains"}

# Pause/resume + configurable check interval (Phase 6, prompt 6.3). A floor, not a ceiling —
# there's no reason to cap how infrequently a target is checked, but an interval too low would
# let a target hammer a site it doesn't control (or this worker's own DB pool) far faster than
# the global default ever would. 30s matches worker/backoff.py's own base delay — the fastest
# cadence anything in this system already retries at.
MIN_CHECK_INTERVAL_SECONDS = 30

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
    # Request customization — all optional, all None/default means "behave exactly as before
    # this feature existed." See ALLOWED_REQUEST_METHODS/ALLOWED_KEYWORD_MATCH_MODES and
    # _validate_request_customization below for what's actually accepted.
    request_method: str | None = None
    request_headers: dict[str, str] | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None
    keyword_match: str | None = None
    keyword_match_mode: str = "contains"
    # None means "use the worker's global CHECK_INTERVAL_SECONDS default." Pause state is
    # deliberately NOT settable here — a target is always created active; pausing is its own
    # state transition via POST /targets/{id}/pause, not a create-time flag.
    check_interval_seconds: int | None = None


class TargetUpdate(BaseModel):
    """PATCH /targets/{id} body. Every field is optional and, per pydantic's exclude_unset
    (see update_target below), only fields actually present in the request JSON are changed —
    an omitted field is left alone, and an explicit `null` clears it. basic_auth_password is
    the one deliberate exception to "null clears it": see update_target's basic-auth handling.

    Deliberately does NOT include `url` — editing a target's URL isn't supported by this
    endpoint (or anywhere else yet); this endpoint exists specifically for the
    request-customization fields below plus `name`. Also does NOT include `paused` — pause
    state changes only through POST /targets/{id}/pause and /resume, never as a silent side
    effect of an unrelated field edit.
    """

    name: str | None = None
    request_method: str | None = None
    request_headers: dict[str, str] | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None
    keyword_match: str | None = None
    keyword_match_mode: str | None = None
    check_interval_seconds: int | None = None


class TargetResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str
    request_method: str | None
    request_headers: dict[str, str] | None
    basic_auth_username: str | None
    keyword_match: str | None
    keyword_match_mode: str
    paused: bool
    check_interval_seconds: int | None
    # Phase 6, prompt 6.4 — the multi-tag shape (a target can carry several labels), not a
    # single group_id. Attach/detach via POST/DELETE /targets/{id}/tags below.
    tags: list[TagResponse]

    class Config:
        from_attributes = True


def _target_to_response(target: Target, tags: list[Tag]) -> TargetResponse:
    """Build a TargetResponse from an ORM Target — shared by create/list/update/pause/resume/
    attach/detach so the field list can't silently drift between call sites.
    basic_auth_password_encrypted is deliberately never included here or anywhere else: the
    decrypted password is never returned by any endpoint, and neither is the encrypted form
    (there's no legitimate reason for a client to see it — an edit form shows only the
    username, per the "blank means unchanged" convention in update_target).

    `tags` is a required, explicit argument rather than read off `target.tags` internally —
    SQLAlchemy's async ORM doesn't support lazy-loading a relationship outside an awaited
    context, so every call site must have already loaded (or, for a brand-new target, simply
    knows to be empty) the tags list itself before calling this function. Forcing it as a
    parameter makes that a call-site decision that can't be silently forgotten."""
    return TargetResponse(
        id=target.id,
        url=target.url,
        name=target.name,
        created_at=target.created_at.isoformat(),
        request_method=target.request_method,
        request_headers=target.request_headers,
        basic_auth_username=target.basic_auth_username,
        keyword_match=target.keyword_match,
        keyword_match_mode=target.keyword_match_mode,
        paused=target.paused,
        check_interval_seconds=target.check_interval_seconds,
        tags=[_tag_to_response(t) for t in tags],
    )


def _validate_check_interval_seconds(check_interval_seconds: int | None) -> None:
    """Shared validation for create and update — a floor only (see MIN_CHECK_INTERVAL_SECONDS),
    no ceiling. Raises HTTPException(400) on violation."""
    if check_interval_seconds is not None and check_interval_seconds < MIN_CHECK_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"check_interval_seconds must be at least {MIN_CHECK_INTERVAL_SECONDS} or omitted",
        )


def _validate_request_customization(
    request_method: str | None,
    keyword_match: str | None,
    keyword_match_mode: str,
    basic_auth_username: str | None,
    basic_auth_password_set: bool,
) -> None:
    """Shared validation for create and update, run against the *resulting* whole state (not
    just whatever fields a PATCH happened to touch) — so a PATCH that only changes one field
    still gets validated against the target's full, merged state. Raises HTTPException(400) on
    any violation; callers must call this before flushing, not after."""
    if request_method is not None and request_method not in ALLOWED_REQUEST_METHODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"request_method must be one of {sorted(ALLOWED_REQUEST_METHODS)} or omitted",
        )
    if keyword_match_mode not in ALLOWED_KEYWORD_MATCH_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"keyword_match_mode must be one of {sorted(ALLOWED_KEYWORD_MATCH_MODES)}",
        )
    if request_method == "HEAD" and keyword_match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="keyword_match requires a request_method that returns a response body "
            "(GET or POST, or omitted) — HEAD has no body to match against",
        )
    if basic_auth_username and not basic_auth_password_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="basic_auth_username requires a basic_auth_password",
        )
    if basic_auth_password_set and not basic_auth_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="basic_auth_password requires a basic_auth_username",
        )


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
    tag: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all targets owned by the authenticated user, each with its full tags list.

    `?tag=<name>` optionally filters to targets carrying a tag with that exact name. Filters by
    name (not tag_id) — the more natural shape for a query-string filter, matching how `region`
    is a plain string identifier elsewhere in this file, not a numeric id a caller would have to
    look up first. The join+filter only restricts *which targets* come back; it doesn't affect
    which tags are eager-loaded for them below — a matched target's response still lists every
    tag it has, not just the one that matched the filter. No explicit Tag.user_id check needed
    on the filter join: a tag can only ever be attached to one of the caller's own targets in
    the first place (enforced at attach time), so any tag reachable via this join already
    belongs to the caller.
    """
    query = (
        select(Target)
        .where(Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
        .order_by(Target.created_at.desc())
    )
    if tag is not None:
        query = query.join(Target.tags).where(Tag.name == tag)
    result = await db.execute(query)
    targets = result.scalars().all()
    return [_target_to_response(t, tags=t.tags) for t in targets]


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

    _validate_request_customization(
        request_method=body.request_method,
        keyword_match=body.keyword_match,
        keyword_match_mode=body.keyword_match_mode,
        basic_auth_username=body.basic_auth_username,
        basic_auth_password_set=bool(body.basic_auth_password),
    )
    _validate_check_interval_seconds(body.check_interval_seconds)

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
        request_method=body.request_method,
        request_headers=body.request_headers or None,
        basic_auth_username=(body.basic_auth_username or None),
        basic_auth_password_encrypted=(
            encrypt_secret(body.basic_auth_password) if body.basic_auth_password else None
        ),
        keyword_match=(body.keyword_match or None),
        keyword_match_mode=body.keyword_match_mode,
        check_interval_seconds=body.check_interval_seconds,
    )
    db.add(target)
    await db.flush()
    await db.refresh(target)
    return _target_to_response(target, tags=[])  # a brand-new target never has any tags yet


@router.patch("/{target_id}", response_model=TargetResponse)
async def update_target(
    target_id: int,
    body: TargetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a target's name, request-customization fields (method/headers/basic-auth/
    keyword-match), and/or check_interval_seconds. Does NOT support changing the URL or pause
    state — url editing isn't supported anywhere yet, and pause/resume are their own dedicated
    endpoints below (a state transition, not a field edit — see their docstrings for why).
    An edit here takes effect on the target's next naturally-scheduled check; this endpoint
    doesn't reach into target_region_schedule to force an immediate recheck (that reset is
    reserved for /resume, a deliberate, narrow exception to target_region_schedule's
    worker-only-write convention — not extended here).

    404 (not 403) for a target that doesn't exist or isn't owned by the caller, same pattern as
    every other target-scoped endpoint.

    Only fields actually present in the request JSON are changed (pydantic's exclude_unset,
    not a bare `is not None` check) — an omitted field is left alone, and most fields can be
    explicitly cleared back to null this way (e.g. `"keyword_match": null` turns content
    matching off). basic_auth_password is the deliberate exception: per the edit-form UX (the
    username is shown back, the password never is), sending it blank or omitting it always
    means "leave the existing password unchanged" — see the basic-auth handling below for how
    to actually remove basic auth entirely vs. just rotate the password vs. rename the
    username.
    """
    result = await db.execute(
        select(Target)
        .where(Target.id == target_id, Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    # Captured now, before db.refresh() below — this endpoint never touches the tags
    # relationship itself, and capturing into a plain list here sidesteps any question about
    # whether a relationship loaded via selectinload survives an explicit refresh().
    tags = list(target.tags)

    provided = body.model_dump(exclude_unset=True)

    if "name" in provided:
        target.name = (body.name.strip() or None) if body.name else None
    if "request_method" in provided:
        target.request_method = body.request_method
    if "request_headers" in provided:
        target.request_headers = body.request_headers
    if "keyword_match" in provided:
        target.keyword_match = body.keyword_match or None
    if "keyword_match_mode" in provided and body.keyword_match_mode is not None:
        target.keyword_match_mode = body.keyword_match_mode
    if "check_interval_seconds" in provided:
        target.check_interval_seconds = body.check_interval_seconds

    if "basic_auth_username" in provided:
        new_username = body.basic_auth_username or None
        if new_username is None:
            # Clearing the username removes basic auth entirely — a lone password with no
            # username to pair it with is meaningless, and _validate_request_customization
            # below would reject it anyway.
            target.basic_auth_username = None
            target.basic_auth_password_encrypted = None
        else:
            target.basic_auth_username = new_username
            if body.basic_auth_password:
                target.basic_auth_password_encrypted = encrypt_secret(body.basic_auth_password)
            # else: username changed/reaffirmed, password left exactly as stored — "blank
            # means unchanged."
    elif body.basic_auth_password:
        # Username untouched this request — only meaningful if basic auth is already
        # configured (a bare password rotation with no username in play, existing or new, is
        # rejected below).
        target.basic_auth_password_encrypted = encrypt_secret(body.basic_auth_password)

    _validate_request_customization(
        request_method=target.request_method,
        keyword_match=target.keyword_match,
        keyword_match_mode=target.keyword_match_mode,
        basic_auth_username=target.basic_auth_username,
        basic_auth_password_set=target.basic_auth_password_encrypted is not None,
    )
    _validate_check_interval_seconds(target.check_interval_seconds)

    await db.flush()
    await db.refresh(target)
    return _target_to_response(target, tags=tags)


@router.post("/{target_id}/pause", response_model=TargetResponse)
async def pause_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause a target: the worker's claim query excludes a paused target entirely (see
    worker/main.py's claim_due_targets — `AND NOT t.paused` in its WHERE clause), across every
    region, until it's resumed. Idempotent — pausing an already-paused target just re-confirms
    the state, no error. 404 (not 403) for a target that doesn't exist or isn't owned by the
    caller, same pattern as every other target-scoped endpoint."""
    result = await db.execute(
        select(Target)
        .where(Target.id == target_id, Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    tags = list(target.tags)  # captured before refresh() — see update_target's comment on this
    target.paused = True
    await db.flush()
    await db.refresh(target)
    return _target_to_response(target, tags=tags)


@router.post("/{target_id}/resume", response_model=TargetResponse)
async def resume_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused target — and make it feel immediate: rather than leaving it to whatever
    next_check_at was last written (which could be minutes away, or arbitrarily stale after a
    long pause), this directly forces every region's schedule row for this target due right
    now. Idempotent — safe to call on a target that isn't currently paused (still resets
    next_check_at, forcing a prompt recheck; harmless).

    Deliberate, narrow exception to target_region_schedule's worker-only-write convention (see
    models/target_region_schedule.py's docstring: "written and read exclusively by the
    worker"): this is the one place the API writes to it directly, specifically so a resume
    doesn't have to wait out a stale schedule. Every other read/write of that table stays
    worker-owned. 404 (not 403) for a target that doesn't exist or isn't owned by the caller,
    same pattern as every other target-scoped endpoint.
    """
    result = await db.execute(
        select(Target)
        .where(Target.id == target_id, Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    tags = list(target.tags)  # captured before refresh() — see update_target's comment on this
    target.paused = False
    await db.execute(
        text("UPDATE target_region_schedule SET next_check_at = now() WHERE target_id = :target_id"),
        {"target_id": target_id},
    )
    await db.flush()
    await db.refresh(target)
    return _target_to_response(target, tags=tags)


class AttachTagBody(BaseModel):
    tag_id: int


@router.post("/{target_id}/tags", response_model=TargetResponse)
async def attach_tag(
    target_id: int,
    body: AttachTagBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach an existing tag (create it first via POST /tags) to a target. Ownership-enforced
    on BOTH sides: the target must belong to the caller AND the tag must belong to the caller —
    either failing returns the same 404 (can't tell which one failed, or that either even
    exists, matching every other ownership check in this file). Idempotent — attaching a tag
    that's already attached is a no-op, not an error."""
    target_result = await db.execute(
        select(Target)
        .where(Target.id == target_id, Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    tag_result = await db.execute(select(Tag).where(Tag.id == body.tag_id, Tag.user_id == current_user.id))
    tag = tag_result.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    if tag not in target.tags:
        target.tags.append(tag)
        await db.flush()
    return _target_to_response(target, tags=list(target.tags))


@router.delete("/{target_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_tag(
    target_id: int,
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach a tag from a target. Ownership-enforced on both — same pattern as attach_tag: a
    target or tag that doesn't exist or isn't owned by the caller is 404. Detaching a tag that
    exists, is owned by the caller, but isn't currently attached to this particular target is
    NOT an error (204) — the end state the caller wanted (not attached) already holds either
    way, same idempotency convention as pause/resume above."""
    target_result = await db.execute(
        select(Target)
        .where(Target.id == target_id, Target.user_id == current_user.id)
        .options(selectinload(Target.tags))
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    tag_result = await db.execute(select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id))
    tag = tag_result.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    if tag in target.tags:
        target.tags.remove(tag)
        await db.flush()
    return None


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


@router.get("/{target_id}/export")
async def export_target_checks(
    target_id: int,
    region: str,
    format: str = "csv",
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export this target's check history for one region as a compliance CSV: a summary
    section (SLA %, incident list) followed by the raw check rows in the requested date range.
    `region` is required — same "never all regions merged" rule as GET /targets/{id}/checks;
    exporting means picking one region, run it again for another if needed. `from`/`to`
    (optional, ISO 8601) bound the range; omitted means unbounded on that side. A single
    synchronous response is fine at this project's real scale — see the export prompt's
    report for the actual row-count numbers behind that call. PDF is not built yet;
    `format` is validated so a caller gets a clear error instead of silently receiving CSV
    under a different label."""
    if format != "csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only format=csv is available today. PDF export is planned but not built yet.",
        )

    result = await db.execute(select(Target).where(Target.id == target_id, Target.user_id == current_user.id))
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")

    query = select(Check).where(Check.target_id == target_id, Check.region == region)
    if from_ is not None:
        query = query.where(Check.checked_at >= from_)
    if to is not None:
        query = query.where(Check.checked_at <= to)
    query = query.order_by(Check.checked_at.asc())

    checks_result = await db.execute(query)
    checks = checks_result.scalars().all()

    csv_text = build_csv(
        target_label=target.name or target.url,
        target_url=target.url,
        region=region,
        range_from=from_,
        range_to=to,
        checks=checks,
    )

    # A fixed, id-based filename rather than interpolating target.name/url directly — both are
    # user-controlled strings, and putting them raw into a Content-Disposition header risks
    # malformed headers (quotes, semicolons are syntactically meaningful there) for no real
    # benefit; the file's own contents already say what target this is.
    filename = f"target-{target_id}-{region}-checks.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
