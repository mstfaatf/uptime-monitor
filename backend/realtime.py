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

The LISTEN connection is opened only while it's needed (see ListenerController): around each
clock-aligned worker burst, while anyone is watching the site, and briefly after either. A
NOTIFY sent while it was closed would otherwise be lost for good, so every time it opens it
first replays any checks committed since the last one it handled (the checks.id watermark).

Also owns downtime/cert-expiry alert evaluation (Phase 4), extended in Phase 6 prompt 6.6 to
fan out to webhooks (backend/webhooks.py) alongside email — see _evaluate_downtime_alert's
docstring for the eligibility/fan-out split that makes webhook delivery independent of the
user's email preference toggle.
"""

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import asyncpg
from sqlalchemy import select, text

import activity
from config import settings
from database import AsyncSessionLocal
from mail import cert_expiry_alert_email, downtime_alert_email, downtime_recovery_email, send_email
from models import AlertHistory, Check, Target, User, Webhook
from webhooks import build_webhook_payload, send_webhook

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "checks_inserted"
# While LISTEN is supposed to be open but isn't (connect failed, or the connection dropped), try
# again this often.
RECONNECT_DELAY_SECONDS = 1

# When the LISTEN connection is held (see ListenerController.should_be_open):
# - from LISTEN_LEAD_SECONDS before each worker burst boundary (multiples of
#   BURST_INTERVAL_SECONDS since the Unix epoch, the same instants the workers compute) until
#   LISTEN_BURST_WINDOW_SECONDS after it. 150s is the workers' 90s burst cap plus time for the
#   checks started in a burst's last pass to finish (up to five redirect hops at the default
#   10s timeout). The 30s lead gives the database time to wake and the connection time to open.
# - while anyone is watching (is_watching), and for LISTEN_QUIET_SECONDS after that stops: a
#   worker in live mode keeps checking until two of its 30s-apart polls say nobody's watching.
# - for LISTEN_QUIET_SECONDS after the last NOTIFY, and while any notification is being handled.
LISTEN_LEAD_SECONDS = 30
LISTEN_BURST_WINDOW_SECONDS = 150
LISTEN_QUIET_SECONDS = 120
# How often the controller re-evaluates when nothing wakes it. In-memory only; no database.
CONTROL_TICK_SECONDS = 1
# Catch-up after a gap reads at most this many checks per query, looping until caught up.
CATCHUP_BATCH_SIZE = 500

# Tags the LISTEN connection in pg_stat_activity so it can be told apart from request-path
# connections ("api") when checking what is keeping the database awake.
LISTEN_APPLICATION_NAME = "api-listen"

# user_id -> the set of queues for that user's currently-connected SSE stream(s) (a user can
# have more than one tab/device open at once).
_subscribers: dict[int, set[asyncio.Queue]] = {}


def subscribe(user_id: int) -> asyncio.Queue:
    """Register a new queue for this user's connection. Call unsubscribe() with the same
    queue when the connection closes, or this leaks memory for the life of the process."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(user_id, set()).add(queue)
    _wake_listener()  # someone is watching now: open LISTEN immediately, not on the next tick
    return queue


def unsubscribe(user_id: int, queue: asyncio.Queue) -> None:
    queues = _subscribers.get(user_id)
    if not queues:
        return
    queues.discard(queue)
    if not queues:
        _subscribers.pop(user_id, None)


def has_subscribers() -> bool:
    """True if any user currently has an SSE stream open. In-memory only, no database access."""
    return bool(_subscribers)


def is_watching() -> bool:
    """Whether anyone is using the site: an open SSE stream, or a cookie-authenticated request
    within WATCHING_WINDOW_SECONDS. In-memory only, no database access. This is the single
    definition shared by GET /internal/watching (which the workers use to choose live mode) and
    the LISTEN controller, so LISTEN is open whenever the workers might be checking in live
    mode."""
    return has_subscribers() or activity.recently_active()


def _publish(user_id: int, payload: dict) -> None:
    """Put payload on every queue this user currently has open. A no-op if the user has no
    connected stream — the update is simply not pushed; GET /targets/status still has it."""
    for queue in _subscribers.get(user_id, ()):
        queue.put_nowait(payload)


async def _evaluate_downtime_alert(
    session, target: Target, check: Check, region: str, user: User, webhooks: list[Webhook]
) -> None:
    """Send (or suppress) a downtime alert for this (target, region), based on the check that
    just landed and what alert_history last recorded.

    **Restructured in Phase 6 prompt 6.6** to separate condition-eligibility (channel-agnostic
    — is this transition worth alerting on at all, per the existing cooldown/alert_history
    check) from channel fan-out (email if user.alert_on_downtime, each webhook independently if
    its own alert_on_downtime is set). Before this, the email-send call and the eligibility
    check were the same code path, so adding webhook delivery would have wrongly coupled it to
    the user's *email* preference specifically — a user with email alerts off but a webhook
    configured would have silently never gotten webhook alerts either, which is not what either
    toggle is supposed to mean.

    Eligibility (channel-agnostic):
      - is_up=false, and (no row or last_state != 'down'), and the cooldown has elapsed since
        the last alert of any kind for this (target, region) -> eligible, event="down".
      - is_up=false, last_state=='down' already -> suppress (still down, already alerted).
      - is_up=true, last_state=='down' -> recovered -> eligible, event="up". No cooldown gate
        on recovery itself (per the original Phase 4 report/prompt) — but the *next* down
        transition still respects the cooldown against this alert's own last_sent_at, which is
        what actually dampens rapid flapping.
      - is_up=true and (no row, or already 'up') -> nothing to do.

    Fan-out: attempts email (if user.alert_on_downtime) and every passed-in webhook (if that
    webhook's own alert_on_downtime is set — `webhooks` is already pre-filtered to this user's
    *enabled* webhooks by the caller) independently. alert_history bookkeeping is written ONCE,
    after fan-out, if AT LEAST ONE channel actually delivered — generalizing the existing
    single-channel rule ("a failed send must not be recorded as alerted, so the next check
    retries") to multiple channels: if nothing got through, nothing is recorded, and the very
    next check retries every channel from scratch. **Known, accepted limitation**: if one
    channel succeeds (e.g. email) and another fails (e.g. a flaky webhook), the successful
    channel's delivery still marks the condition "alerted," so the failed channel is NOT
    individually retried on the next check — alert_history tracks "was this transition alerted
    at all," not per-channel delivery status. A per-channel retry/delivery-log system would be
    a materially bigger feature than what's being built here.

    Does not commit — the caller commits once after both alert types are evaluated.
    """
    result = await session.execute(
        select(AlertHistory).where(
            AlertHistory.target_id == target.id,
            AlertHistory.region == region,
            AlertHistory.alert_type == "downtime",
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not check.is_up:
        if row is not None and row.last_state == "down":
            return  # still down since the last alert — suppress
        if row is not None and (now - row.last_sent_at).total_seconds() < settings.DOWNTIME_ALERT_COOLDOWN_SECONDS:
            return  # a flapping target can't re-trigger faster than the cooldown
        event = "down"
    elif row is not None and row.last_state == "down":
        event = "up"
    else:
        return  # is_up=true and no row, or already 'up' — nothing to do, no bookkeeping needed

    target_label = target.name or target.url
    detail_url = f"{settings.FRONTEND_URL}/dashboard/{target.id}"
    settings_url = f"{settings.FRONTEND_URL}/settings"
    checked_at = check.checked_at.isoformat() if check.checked_at else "unknown"

    delivered = False

    if user.alert_on_downtime:
        if event == "down":
            subject, body = downtime_alert_email(
                target_label=target_label,
                target_url=target.url,
                region=region,
                checked_at=checked_at,
                error=check.error,
                detail_url=detail_url,
                settings_url=settings_url,
            )
        else:
            subject, body = downtime_recovery_email(
                target_label=target_label,
                target_url=target.url,
                region=region,
                checked_at=checked_at,
                detail_url=detail_url,
                settings_url=settings_url,
            )
        if await send_email(user.email, subject, body):
            delivered = True

    webhook_event = "target.down" if event == "down" else "target.up"
    payload = build_webhook_payload(webhook_event, target, region, check, detail_url)
    for webhook in webhooks:
        if webhook.alert_on_downtime:
            if await send_webhook(webhook.url, webhook.secret, payload):
                delivered = True

    if not delivered:
        # No channel actually got through (bad Resend key, every webhook unreachable, or both
        # gated off entirely) — must NOT be recorded as "already alerted": doing so would
        # permanently suppress the real alert via the "still down" check above, with no retry,
        # even after whatever broke delivery is fixed. Leaving no row (or an untouched existing
        # one) means the very next check retries every channel from scratch.
        return
    if row is None:
        session.add(
            AlertHistory(target_id=target.id, region=region, alert_type="downtime", last_state=event, last_sent_at=now)
        )
    else:
        row.last_state = event
        row.last_sent_at = now


async def _evaluate_cert_expiry_alert(
    session, target: Target, check: Check, region: str, user: User, webhooks: list[Webhook]
) -> None:
    """Send (or suppress) a cert-expiry alert for this (target, region). Fires once when
    tls_cert_days_remaining first crosses <= CERT_EXPIRY_WARN_DAYS, then re-reminds at most
    every CERT_EXPIRY_REMINDER_COOLDOWN_DAYS while still expiring and unrenewed. Renewal
    (a changed tls_cert_expires_at from what alert_history last recorded) resets eligibility
    immediately, regardless of the reminder cooldown, since it's a genuinely new expiry window
    worth its own first alert.

    Restructured the same way as _evaluate_downtime_alert above (Phase 6 prompt 6.6): the
    eligibility check below is channel-agnostic, fan-out to email/webhooks happens
    independently afterward, and alert_history is written once if any channel delivered — see
    that function's docstring for the full reasoning, including the known per-channel-retry
    limitation. Does not commit — same caller-commits contract as the downtime evaluator.
    """
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

    detail_url = f"{settings.FRONTEND_URL}/dashboard/{target.id}"
    settings_url = f"{settings.FRONTEND_URL}/settings"

    delivered = False

    if user.alert_on_cert_expiry:
        subject, body = cert_expiry_alert_email(
            target_label=target.name or target.url,
            target_url=target.url,
            region=region,
            days_remaining=days_remaining,
            expires_at=check.tls_cert_expires_at.isoformat(),
            issuer=check.tls_cert_issuer,
            detail_url=detail_url,
            settings_url=settings_url,
        )
        if await send_email(user.email, subject, body):
            delivered = True

    payload = build_webhook_payload("target.cert_expiring", target, region, check, detail_url)
    for webhook in webhooks:
        if webhook.alert_on_cert_expiry:
            if await send_webhook(webhook.url, webhook.secret, payload):
                delivered = True

    if not delivered:
        return  # same reasoning as the downtime evaluator — retry every channel next check
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


async def _handle_notification(payload: str) -> int | None:
    """Resolve a notified target_id to its owner and publish the same status payload the
    REST endpoint would return for it (every region's latest check), so the frontend never
    needs a follow-up fetch. payload is "{target_id}:{region}"; region is carried through into
    the published event purely to say which region's check triggered it.

    Returns the id of that region's latest check (the one evaluated), or None if there was
    nothing to handle, so the LISTEN controller can advance its catch-up watermark.

    Safe to run more than once for the same check, which the catch-up replay relies on: alert
    evaluation compares against alert_history (still down / already recovered / cert reminder
    cooldown) and sends nothing new, and a repeated SSE push just re-sends the same state."""
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
                    # Fetched once here and passed to both evaluators — only *enabled*
                    # webhooks are candidates at all; each evaluator further filters by its
                    # own alert_on_downtime/alert_on_cert_expiry toggle (see their docstrings).
                    webhooks_result = await session.execute(
                        select(Webhook).where(Webhook.user_id == target.user_id, Webhook.enabled.is_(True))
                    )
                    webhooks = list(webhooks_result.scalars().all())
                    await _evaluate_downtime_alert(session, target, check, region, user, webhooks)
                    await _evaluate_cert_expiry_alert(session, target, check, region, user, webhooks)
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
    return check.id if check is not None else None


async def _connect_listen() -> asyncpg.Connection:
    """Open the LISTEN connection on settings.listen_asyncpg_url, not the pooled DATABASE_URL: a
    pooled connection (Neon's default in production) doesn't reliably deliver NOTIFYs to a
    LISTEN session, since the pool can swap the physical backend between queries. See
    config.py's LISTEN_DATABASE_URL."""
    return await asyncpg.connect(
        settings.listen_asyncpg_url, server_settings={"application_name": LISTEN_APPLICATION_NAME}
    )


async def _fetch_max_check_id() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT coalesce(max(id), 0) FROM checks"))
        return int(result.scalar_one())


async def _fetch_checks_after(after_id: int, limit: int) -> list[tuple[int, int, str]]:
    """(id, target_id, region) of checks with id > after_id, oldest first, at most `limit`."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT id, target_id, region FROM checks WHERE id > :after ORDER BY id LIMIT :limit"),
            {"after": after_id, "limit": limit},
        )
        return [(int(r[0]), int(r[1]), str(r[2])) for r in result.all()]


class ListenerController:
    """Holds the LISTEN connection only while it's needed, and replays anything missed.

    Postgres doesn't queue a NOTIFY for a listener that isn't connected, so a check committed
    while LISTEN is closed would lose its SSE push and, worse, its alert evaluation. Two things
    guard against that:

    - should_be_open() keeps the connection open whenever a worker might be writing checks:
      around every clock-aligned burst, whenever is_watching() is true (the exact predicate the
      workers use to go live), shortly after either, after any recent NOTIFY, and while any
      notification is still being handled.
    - Every time the connection opens (first open, reopen, or reconnect after a drop) it runs
      LISTEN first, then replays every check with an id above the watermark (the last check id
      handled) through _handle_notification, oldest first, in batches. Handled NOTIFYs advance
      the watermark too. A replay of something already handled is harmless (see
      _handle_notification's docstring).

    Everything the controller touches outside memory is injected, so the tests can drive it with
    a fake clock and fake connection.
    """

    def __init__(
        self,
        *,
        burst_interval: int,
        connect: Callable[[], Awaitable[asyncpg.Connection]] = _connect_listen,
        watching: Callable[[], bool] = is_watching,
        handle: Callable[[str], Awaitable[int | None]] = _handle_notification,
        fetch_max_check_id: Callable[[], Awaitable[int]] = _fetch_max_check_id,
        fetch_checks_after: Callable[[int, int], Awaitable[list[tuple[int, int, str]]]] = _fetch_checks_after,
        now: Callable[[], float] = time.time,
    ):
        self._burst_interval = burst_interval
        self._connect = connect
        self._watching = watching
        self._handle = handle
        self._fetch_max_check_id = fetch_max_check_id
        self._fetch_checks_after = fetch_checks_after
        self._now = now
        self._conn = None
        self.watermark: int | None = None
        self._last_notify_at: float | None = None
        self._last_watching_at: float | None = None
        self._in_flight = 0
        self._tasks: set[asyncio.Task] = set()
        self._next_attempt_at = 0.0
        self._wake = asyncio.Event()

    @property
    def is_open(self) -> bool:
        return self._conn is not None and not self._conn.is_closed()

    def wake(self) -> None:
        """Re-evaluate now instead of at the next tick. Safe to call from sync code."""
        self._wake.set()

    def in_burst_window(self, now: float) -> bool:
        previous = math.floor(now / self._burst_interval) * self._burst_interval
        upcoming = previous + self._burst_interval
        return now >= upcoming - LISTEN_LEAD_SECONDS or now <= previous + LISTEN_BURST_WINDOW_SECONDS

    def should_be_open(self) -> bool:
        now = self._now()
        if self._watching():
            self._last_watching_at = now
            return True
        if self._in_flight:
            return True
        if self.in_burst_window(now):
            return True
        if self._last_watching_at is not None and now - self._last_watching_at < LISTEN_QUIET_SECONDS:
            return True
        if self._last_notify_at is not None and now - self._last_notify_at < LISTEN_QUIET_SECONDS:
            return True
        return False

    async def initialize_watermark(self) -> None:
        try:
            self.watermark = await self._fetch_max_check_id()
        except Exception:
            logger.exception("Couldn't read the latest check id; it will be read on the first LISTEN open")

    async def step(self) -> None:
        """One open/close decision."""
        if self._conn is not None and self._conn.is_closed():
            logger.warning("LISTEN connection closed; reconnecting")
            self._conn = None
        should_open = self.should_be_open()
        if should_open and self._conn is None:
            if self._now() >= self._next_attempt_at:
                await self._open()
        elif not should_open and self._conn is not None:
            await self._close()

    async def _open(self) -> None:
        conn = None
        try:
            conn = await self._connect()
            await conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
        except Exception:
            logger.exception("LISTEN connection failed; reconnecting shortly")
            self._next_attempt_at = self._now() + RECONNECT_DELAY_SECONDS
            if conn is not None:
                with contextlib.suppress(Exception):
                    await conn.close()
            return
        self._conn = conn
        logger.info("Listening for check notifications on %r", NOTIFY_CHANNEL)
        await self._catch_up()

    async def _close(self) -> None:
        conn, self._conn = self._conn, None
        logger.info("Closing the LISTEN connection: nobody watching and no recent check activity")
        try:
            await conn.close()
        except Exception:
            logger.exception("Error closing the LISTEN connection")

    async def _catch_up(self) -> None:
        """Replay checks committed since the watermark. LISTEN is already registered, so
        anything committed from here on also arrives as a NOTIFY; replaying it twice is safe."""
        self._in_flight += 1
        try:
            if self.watermark is None:
                self.watermark = await self._fetch_max_check_id()
                return
            replayed = 0
            while True:
                rows = await self._fetch_checks_after(self.watermark, CATCHUP_BATCH_SIZE)
                if not rows:
                    break
                # The handler always evaluates a (target, region)'s *latest* check, so each pair
                # needs handling once per batch, in the order of its newest check.
                newest: dict[tuple[int, str], int] = {}
                for check_id, target_id, region in rows:
                    newest[(target_id, region)] = check_id
                for (target_id, region), check_id in sorted(newest.items(), key=lambda item: item[1]):
                    await self._handle(f"{target_id}:{region}")
                    replayed += 1
                self.watermark = max(self.watermark, rows[-1][0])
                if len(rows) < CATCHUP_BATCH_SIZE:
                    break
            if replayed:
                logger.info("Caught up on %d missed check notification(s)", replayed)
        except Exception:
            # The watermark only moves past fully handled batches, so the next open retries.
            logger.exception("Catch-up after (re)opening LISTEN failed; will retry on the next open")
        finally:
            self._in_flight -= 1

    def _on_notify(self, connection, pid, channel, payload) -> None:
        # asyncpg calls this synchronously from its own read loop; hand off to a task rather
        # than doing async database work in the callback.
        self._last_notify_at = self._now()
        self._in_flight += 1
        task = asyncio.create_task(self._run_handler(payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_handler(self, payload: str) -> None:
        try:
            check_id = await self._handle(payload)
            if check_id is not None and (self.watermark is None or check_id > self.watermark):
                self.watermark = check_id
        except Exception:
            logger.exception("Handling check notification %r failed", payload)
        finally:
            self._in_flight -= 1
            self.wake()

    async def run(self) -> None:
        """Runs for the life of the process (started from main.py's lifespan)."""
        await self.initialize_watermark()
        try:
            while True:
                self._wake.clear()
                try:
                    await self.step()
                except Exception:
                    logger.exception("LISTEN controller step failed")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=CONTROL_TICK_SECONDS)
        finally:
            if self._conn is not None:
                with contextlib.suppress(Exception):
                    await self._conn.close()
                self._conn = None


_controller: ListenerController | None = None


def _wake_listener() -> None:
    if _controller is not None:
        _controller.wake()


def start_listener_controller() -> ListenerController:
    """Create the process's LISTEN controller and hook it up to activity, so a sign-in opens
    LISTEN immediately. The caller runs controller.run() as a background task."""
    global _controller
    _controller = ListenerController(burst_interval=settings.BURST_INTERVAL_SECONDS)
    activity.add_listener(_wake_listener)
    return _controller


def stop_listener_controller() -> None:
    global _controller
    activity.remove_listener(_wake_listener)
    _controller = None
