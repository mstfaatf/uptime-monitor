"""In-process pub/sub that pushes check-result updates to connected SSE clients.

The worker NOTIFYs (via pg_notify) with a target_id after each check commits. This module
holds one long-lived LISTEN connection, resolves each notified target_id to its owning
user_id, and forwards the event only to that user's connected SSE queue(s) — routers/targets.py's
/targets/stream endpoint never sees another user's data, because it's never put in its queue in
the first place. This is what makes the ownership guarantee hold for push, not just for the
regular REST endpoints.

NOTIFY_CHANNEL must match the literal string the worker NOTIFYs on (worker/main.py). The two
services are deployed independently (see backend/security/ssrf.py's docstring for the same
"deliberately duplicated, not shared" reasoning), so this is kept in sync by hand, not import.
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
    REST endpoint would return for it, so the frontend never needs a follow-up fetch."""
    try:
        target_id = int(payload)
    except (TypeError, ValueError):
        logger.warning("Ignoring malformed check notification payload: %r", payload)
        return

    # Local import: routers.targets imports this module (to call subscribe/unsubscribe), so a
    # top-level import here would be circular. By the time this coroutine actually runs, both
    # modules are already fully loaded, so a local import is safe and cheap (module lookup,
    # not re-execution).
    from routers.targets import _latest_check_query, build_target_status_payload

    async with AsyncSessionLocal() as session:
        result = await session.execute(_latest_check_query(target_id=target_id))
        row = result.first()
        if row is None:
            # The target was deleted between the NOTIFY firing and this lookup running —
            # nothing to push, and (since it's gone) no owner to push it to.
            return
        target, check = row
        payload_dict = build_target_status_payload(target, check)

    _publish(target.user_id, {"type": "check_update", "target": payload_dict})


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
