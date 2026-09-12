"""Worker: per-target scheduled HTTP checks, results stored in checks table.

Each target has its own next_check_at; a cycle only checks targets that are currently due,
rather than checking every target on every cycle. A successful check reschedules the target at
the normal cadence (CHECK_INTERVAL_SECONDS); a failed check backs off (see backoff.py) so a
persistently-down target isn't retried on the same tight schedule as a healthy one.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx

from backoff import compute_backoff_seconds
from config import settings
from checker import check_url
from ssrf import is_url_blocked

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Bounds how many checks run concurrently within one cycle. Picked from the middle of the
# 10-20 range proposed in the Phase 1 familiarization report: high enough that a cycle over a
# few dozen targets finishes in roughly one round-trip instead of N sequential ones, low enough
# that a single worker process doesn't open dozens of simultaneous outbound connections/DNS
# lookups (against sites we don't control) or DB connections (against our own pool) all at once.
CHECK_CONCURRENCY = 15

# How often the worker polls the DB for targets whose next_check_at is due. Deliberately much
# shorter than CHECK_INTERVAL_SECONDS (the normal per-target recheck cadence): with per-target
# scheduling, a failing target's backoff delay can be as short as ~30s (see backoff.py), and a
# 300s outer poll would flatten that back down to "retry every 5 minutes regardless," defeating
# the point of backing off gradually. A 5s poll against an indexed next_check_at column is
# trivial at this scale (a single user's targets).
SCHEDULER_TICK_SECONDS = 5


async def get_due_targets(conn: asyncpg.Connection) -> list[dict]:
    """Return {id, url, consecutive_failures} for targets whose next_check_at has arrived."""
    rows = await conn.fetch(
        "SELECT id, url, consecutive_failures FROM targets WHERE next_check_at <= now()"
    )
    return [dict(row) for row in rows]


async def insert_check(
    conn: asyncpg.Connection,
    target_id: int,
    checked_at: datetime,
    status_code: int | None,
    latency_ms: int | None,
    is_up: bool,
    error: str | None,
) -> None:
    """Insert one row into checks — the honest historical record of this attempt, written
    unconditionally regardless of how the target gets rescheduled afterwards."""
    await conn.execute(
        """
        INSERT INTO checks (target_id, checked_at, status_code, latency_ms, is_up, error)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        target_id,
        checked_at,
        status_code,
        latency_ms,
        is_up,
        error or None,
    )


async def reschedule_target(
    conn: asyncpg.Connection,
    target_id: int,
    is_up: bool,
    consecutive_failures_before: int,
) -> None:
    """
    Update the target's scheduling state after a check. Success resets the failure streak and
    returns to the normal CHECK_INTERVAL_SECONDS cadence; failure increments the streak and
    schedules the next attempt using exponential backoff with jitter.
    """
    if is_up:
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=settings.CHECK_INTERVAL_SECONDS)
        await conn.execute(
            "UPDATE targets SET consecutive_failures = 0, next_check_at = $2 WHERE id = $1",
            target_id,
            next_check_at,
        )
    else:
        new_failures = consecutive_failures_before + 1
        delay_seconds = compute_backoff_seconds(new_failures)
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        await conn.execute(
            "UPDATE targets SET consecutive_failures = $2, next_check_at = $3 WHERE id = $1",
            target_id,
            new_failures,
            next_check_at,
        )


async def check_one(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    target_id: int,
    url: str,
    consecutive_failures_before: int,
) -> None:
    """Check a single target, bounded by the semaphore, record its result, and reschedule it."""
    async with semaphore:
        try:
            # is_url_blocked() does a blocking socket.getaddrinfo() call — run it off the event
            # loop so it doesn't stall every other in-flight check under this same semaphore.
            blocked, reason = await asyncio.to_thread(is_url_blocked, url)
            if blocked:
                result = {
                    "checked_at": datetime.now(timezone.utc),
                    "status_code": None,
                    "latency_ms": None,
                    "is_up": False,
                    "error": reason,
                }
                logger.info("Target %s blocked (SSRF): %s", target_id, reason)
            else:
                result = await check_url(client, url)
                logger.info(
                    "Target %s: %s %s ms is_up=%s %s",
                    target_id,
                    result["status_code"],
                    result["latency_ms"],
                    result["is_up"],
                    result["error"] or "",
                )

            async with pool.acquire() as conn, conn.transaction():
                # Write the honest result first — is_up=False for a failed check is recorded
                # unconditionally here, regardless of what backoff decides about *when* to
                # check again next.
                await insert_check(
                    conn,
                    target_id=target_id,
                    checked_at=result["checked_at"],
                    status_code=result["status_code"],
                    latency_ms=result["latency_ms"],
                    is_up=result["is_up"],
                    error=result["error"],
                )
                await reschedule_target(conn, target_id, result["is_up"], consecutive_failures_before)
        except Exception:
            # A target can be deleted by its owner between being selected for this cycle and
            # this check completing — most concretely, the INSERT above would then violate the
            # checks.target_id foreign key once the target row is gone. Rather than let that
            # (or any other unexpected per-target error) propagate out of asyncio.gather() and
            # cancel every other concurrently in-flight check this cycle, log it and move on:
            # a deleted target simply won't be selected again (its row, and next_check_at with
            # it, no longer exists); any other target's state is untouched by this one failing.
            logger.exception(
                "Check failed for target %s (it may have been deleted mid-check)", target_id
            )


async def run_cycle(pool: asyncpg.Pool, client: httpx.AsyncClient) -> None:
    """Fetch targets currently due for a check and check them concurrently (bounded by
    CHECK_CONCURRENCY) — targets not yet due are left alone until their next_check_at arrives."""
    async with pool.acquire() as conn:
        targets = await get_due_targets(conn)
    if not targets:
        logger.debug("No targets due for a check")
        return
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    await asyncio.gather(
        *(
            check_one(pool, client, semaphore, row["id"], row["url"], row["consecutive_failures"])
            for row in targets
        )
    )


async def main() -> None:
    logger.info(
        "Worker starting (interval=%ss, tick=%ss, timeout=%ss, concurrency=%s)",
        settings.CHECK_INTERVAL_SECONDS,
        SCHEDULER_TICK_SECONDS,
        settings.HTTP_TIMEOUT_SECONDS,
        CHECK_CONCURRENCY,
    )
    pool = await asyncpg.create_pool(settings.asyncpg_database_url)
    try:
        async with httpx.AsyncClient(
            timeout=settings.HTTP_TIMEOUT_SECONDS, verify=settings.HTTP_VERIFY_SSL
        ) as client:
            while True:
                try:
                    await run_cycle(pool, client)
                except Exception as e:
                    logger.exception("Cycle failed: %s", e)
                await asyncio.sleep(SCHEDULER_TICK_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
