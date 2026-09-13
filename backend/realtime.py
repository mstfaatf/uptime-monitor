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

import asyncpg
from sqlalchemy import select

from config import settings
from database import AsyncSessionLocal
from models import Check, Target

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

    _publish(target.user_id, {"type": "check_update", "region": region, "target": payload_dict})


async def run_listener() -> None:
    """
    Hold one Postgres LISTEN connection open for the life of the process. If it's ever lost
    (network blip, Postgres restart, connection recycling) reconnect after a fixed delay —
    this loop has no other way to learn about new checks, so it must never give up permanently,
    only wait and retry. Intended to run as a single background task started at app startup
    (see main.py's lifespan) and cancelled at shutdown.
    """
    while True:
        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(settings.asyncpg_database_url)

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
