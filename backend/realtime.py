"""In-process pub/sub that pushes check-result updates to connected SSE clients.

The worker NOTIFYs (via pg_notify) with a "{target_id}:{region}" payload after each check
commits — see backend/alembic/versions/006_add_region_and_target_schedule.py for why a check
now belongs to a region. This module holds one long-lived LISTEN connection, resolves each
notified target_id to its owning user_id, and forwards the event only to that user's connected
SSE queue(s) — routers/targets.py's /targets/stream endpoint never sees another user's data,
because it's never put in its queue in the first place. This is what makes the ownership
guarantee hold for push, not just for the regular REST endpoints; it holds regardless of which
region triggered the notification, since resolution is by target_id, not by region.

The pushed payload always carries the target's *complete* latest_checks (every region's most
recent result, the same shape GET /targets/status returns) rather than just the one region
that changed — `region` is included at the top level purely to say which region's check
triggered this particular event, not to scope what data comes back. This preserves the
existing "one shape decides what a target status looks like" invariant (see
build_target_status_payload in routers/targets.py) instead of forcing the frontend to merge
partial per-region deltas.

NOTIFY_CHANNEL and the "{target_id}:{region}" payload format must match what the worker
NOTIFYs (worker/main.py). The two services are deployed independently (see
backend/security/ssrf.py's docstring for the same "deliberately duplicated, not shared"
reasoning), so this is kept in sync by hand, not import.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from mail import cert_expiry_alert_email, downtime_alert_email, downtime_recovery_email, send_email
from models import AlertHistory, Check, Target, User

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "checks_inserted"
RECONNECT_DELAY_SECONDS = 5

# user_id -> the set of queues for that user's currently-connected SSE stream(s) (a user can
# have more than one tab/device open at once).
_subscribers: dict[int, set[asyncio.Queue]] = {}


def subscribe(user_id: int) -> asyncio.Queue:
    """Register a new queue for this user's connection. Call unsubscribe() with the same
    queue when the connection closes, or this leaks memory for the life of the process."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(user_id, set()).add(queue)
    return queue


def unsubscribe(user_id: int, queue: asyncio.Queue) -> None:
    queues = _subscribers.get(user_id)
    if not queues:
        return
    queues.discard(queue)
    if not queues:
        _subscribers.pop(user_id, None)


def _publish(user_id: int, payload: dict) -> None:
    """Put payload on every queue this user currently has open. A no-op if the user has no
    connected stream — the update is simply not pushed; GET /targets/status still has it."""
    for queue in _subscribers.get(user_id, ()):
        queue.put_nowait(payload)


async def _evaluate_downtime_alert(session, target: Target, check: Check, region: str, user: User) -> None:
    """Send (or suppress) a downtime alert for this (target, region), based on the check that
    just landed and what alert_history last recorded — see the Phase 4 design report:
      - is_up=false, and (no row or last_state != 'down'), and the cooldown has elapsed since
        the last email of any kind for this (target, region) -> send, upsert last_state='down'.
      - is_up=false, last_state=='down' already -> suppress (still down, already alerted).
      - is_up=true, last_state=='down' -> recovered; send a "back up" email, upsert
        last_state='up'. No cooldown gate on recovery itself (per the Phase 4 report/prompt) —
        but the *next* down transition still respects the cooldown against this email's own
        last_sent_at, which is what actually dampens rapid flapping.
    Does not commit — the caller commits once after both alert types are evaluated.
    """
    if not user.alert_on_downtime:
        return

    result = await session.execute(
        select(AlertHistory).where(
            AlertHistory.target_id == target.id,
            AlertHistory.region == region,
            AlertHistory.alert_type == "downtime",
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    target_label = target.name or target.url
    detail_url = f"{settings.FRONTEND_URL}/dashboard/{target.id}"
    settings_url = f"{settings.FRONTEND_URL}/settings"
    checked_at = check.checked_at.isoformat() if check.checked_at else "unknown"

    if not check.is_up:
        if row is not None and row.last_state == "down":
            return  # still down since the last alert — suppress
        if row is not None and (now - row.last_sent_at).total_seconds() < settings.DOWNTIME_ALERT_COOLDOWN_SECONDS:
            return  # a flapping target can't re-trigger faster than the cooldown
        subject, body = downtime_alert_email(
            target_label=target_label,
            target_url=target.url,
            region=region,
            checked_at=checked_at,
            error=check.error,
            detail_url=detail_url,
            settings_url=settings_url,
        )
        sent = await send_email(user.email, subject, body)
        if not sent:
            # A failed send (bad key, Resend outage, or — found live in prompt 4.6.1 — a
            # misconfigured async client) must NOT be recorded as "already alerted": doing so
            # would permanently suppress the real alert via the "still down" check above, with
            # no retry, even after whatever broke the send is fixed. Leaving no row (or an
            # untouched existing one) means the very next check retries this from scratch.
            return
        if row is None:
            session.add(
                AlertHistory(target_id=target.id, region=region, alert_type="downtime", last_state="down", last_sent_at=now)
            )
        else:
            row.last_state = "down"
            row.last_sent_at = now
    elif row is not None and row.last_state == "down":
        subject, body = downtime_recovery_email(
            target_label=target_label,
            target_url=target.url,
            region=region,
            checked_at=checked_at,
            detail_url=detail_url,
            settings_url=settings_url,
        )
        sent = await send_email(user.email, subject, body)
        if not sent:
            return  # same reasoning as above — retry on the next check, don't fake success
        row.last_state = "up"
        row.last_sent_at = now
    # else: is_up=true and no row, or already 'up' — nothing to do, no bookkeeping needed.


async def _evaluate_cert_expiry_alert(session, target: Target, check: Check, region: str, user: User) -> None:
    """Send (or suppress) a cert-expiry alert for this (target, region). Fires once when
    tls_cert_days_remaining first crosses <= CERT_EXPIRY_WARN_DAYS, then re-reminds at most
    every CERT_EXPIRY_REMINDER_COOLDOWN_DAYS while still expiring and unrenewed. Renewal
    (a changed tls_cert_expires_at from what alert_history last recorded) resets eligibility
    immediately, regardless of the reminder cooldown, since it's a genuinely new expiry window
    worth its own first alert. Does not commit — same caller-commits contract as the downtime
    evaluator above."""
    if not user.alert_on_cert_expiry:
        return
    if check.tls_cert_expires_at is None:
        return  # no cert data on this check (plain http, or a failed check)

    days_remaining = (check.tls_cert_expires_at - datetime.now(timezone.utc)).days
    if days_remaining > settings.CERT_EXPIRY_WARN_DAYS:
        return

    result = await session.execute(
        select(AlertHistory).where(
            AlertHistory.target_id == target.id,
            AlertHistory.region == region,
            AlertHistory.alert_type == "cert_expiry",
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    renewed = (
        row is not None
        and row.last_cert_expires_at is not None
        and row.last_cert_expires_at != check.tls_cert_expires_at
    )
    cooldown_elapsed = row is not None and (
        now - row.last_sent_at >= timedelta(days=settings.CERT_EXPIRY_REMINDER_COOLDOWN_DAYS)
    )

    if row is not None and not renewed and not cooldown_elapsed:
        return  # already reminded recently about this same cert — suppress

    subject, body = cert_expiry_alert_email(
        target_label=target.name or target.url,
        target_url=target.url,
        region=region,
        days_remaining=days_remaining,
        expires_at=check.tls_cert_expires_at.isoformat(),
        issuer=check.tls_cert_issuer,
        detail_url=f"{settings.FRONTEND_URL}/dashboard/{target.id}",
        settings_url=f"{settings.FRONTEND_URL}/settings",
    )
    sent = await send_email(user.email, subject, body)
    if not sent:
        return  # same reasoning as the downtime evaluator — a failed send retries next check
    if row is None:
        session.add(
            AlertHistory(
                target_id=target.id,
                region=region,
                alert_type="cert_expiry",
                last_state="expiring",
                last_sent_at=now,
                last_cert_expires_at=check.tls_cert_expires_at,
            )
        )
    else:
        row.last_state = "expiring"
        row.last_sent_at = now
        row.last_cert_expires_at = check.tls_cert_expires_at


async def _handle_notification(payload: str) -> None:
    """Resolve a notified target_id to its owner and publish the same status payload the
    REST endpoint would return for it (every region's latest check), so the frontend never
    needs a follow-up fetch. payload is "{target_id}:{region}"; region is carried through into
    the published event purely to say which region's check triggered it."""
    target_id_str, sep, region = payload.partition(":")
    if not sep:
        logger.warning("Ignoring malformed check notification payload (missing region): %r", payload)
        return
    try:
        target_id = int(target_id_str)
    except ValueError:
        logger.warning("Ignoring malformed check notification payload: %r", payload)
        return

    # Local import: routers.targets imports this module (to call subscribe/unsubscribe), so a
    # top-level import here would be circular. By the time this coroutine actually runs, both
    # modules are already fully loaded, so a local import is safe and cheap (module lookup,
    # not re-execution).
    from routers.targets import _group_checks_by_target, _latest_checks_per_region_query, build_target_status_payload

    async with AsyncSessionLocal() as session:
        result = await session.execute(_latest_checks_per_region_query(target_id=target_id))
        rows = result.all()
        if not rows:
            # The target was deleted between the NOTIFY firing and this lookup running —
            # nothing to push, and (since it's gone) no owner to push it to.
            return
        targets_by_id, checks_by_target, failures_by_target = _group_checks_by_target(rows)
        target = targets_by_id[target_id]
        payload_dict = build_target_status_payload(target, checks_by_target[target_id], failures_by_target[target_id])

        # Alerting: evaluated in this same session/lookup, which already resolved target ->
        # owner and has the fresh Check row for the region that actually triggered this
        # notification — no second query round-trip needed, and this stays region-scoped by
        # construction (it only ever evaluates *this* region's check against *this* region's
        # alert_history rows, never a target-wide collapsed state). Wrapped in its own
        # try/except: a Resend failure (or any other error here) must never block or corrupt
        # the SSE push below, which is this handler's primary purpose and must always run.
        check = checks_by_target[target_id].get(region)
        if check is not None:
            try:
                user_result = await session.execute(select(User).where(User.id == target.user_id))
                user = user_result.scalar_one_or_none()
                if user is not None:
                    await _evaluate_downtime_alert(session, target, check, region, user)
                    await _evaluate_cert_expiry_alert(session, target, check, region, user)
                    await session.commit()
            except Exception:
                logger.exception(
                    "Alert evaluation failed for target %s region %s (check result was still "
                    "recorded and the SSE push below still runs; only the alert email/bookkeeping "
                    "for this event may be missing)",
                    target_id,
                    region,
                )

    _publish(target.user_id, {"type": "check_update", "region": region, "target": payload_dict})


async def run_listener() -> None:
    """
    Hold one Postgres LISTEN connection open for the life of the process. If it's ever lost
    (network blip, Postgres restart, connection recycling) reconnect after a fixed delay —
    this loop has no other way to learn about new checks, so it must never give up permanently,
    only wait and retry. Intended to run as a single background task started at app startup
    (see main.py's lifespan) and cancelled at shutdown.

    Uses settings.listen_asyncpg_url, not the pooled settings.asyncpg_database_url — a pooled
    connection (Neon's default DATABASE_URL in production) doesn't reliably deliver NOTIFYs to
    a LISTEN session, since the pool can swap the physical backend between queries. See
    config.py's LISTEN_DATABASE_URL for the full explanation.
    """
    while True:
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(settings.listen_asyncpg_url)

            def _on_notify(connection, pid, channel, payload) -> None:
                # asyncpg calls this synchronously from its own read loop — hand off to a task
                # rather than doing async DB work directly in the callback.
                asyncio.create_task(_handle_notification(payload))

            await conn.add_listener(NOTIFY_CHANNEL, _on_notify)
            logger.info("Listening for check notifications on %r", NOTIFY_CHANNEL)
            while not conn.is_closed():
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            logger.warning("LISTEN connection closed; reconnecting")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LISTEN connection failed; reconnecting shortly")
        finally:
            if conn is not None and not conn.is_closed():
                await conn.close()
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)
