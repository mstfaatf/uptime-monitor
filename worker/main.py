"""Worker: periodic HTTP checks for all targets, results stored in checks table."""

import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

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


async def get_targets(conn: asyncpg.Connection) -> list[dict]:
    """Return list of {id, url} for all targets."""
    rows = await conn.fetch("SELECT id, url FROM targets")
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
    """Insert one row into checks."""
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


async def check_one(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    target_id: int,
    url: str,
) -> None:
    """Check a single target, bounded by the semaphore, and record its result."""
    async with semaphore:
        # is_url_blocked() does a blocking socket.getaddrinfo() call — run it off the event
        # loop so it doesn't stall every other in-flight check under this same semaphore.
        blocked, reason = await asyncio.to_thread(is_url_blocked, url)
        if blocked:
            async with pool.acquire() as conn:
                await insert_check(
                    conn,
                    target_id=target_id,
                    checked_at=datetime.now(timezone.utc),
                    status_code=None,
                    latency_ms=None,
                    is_up=False,
                    error=reason,
                )
            logger.info("Target %s blocked (SSRF): %s", target_id, reason)
            return

        result = await check_url(client, url)
        async with pool.acquire() as conn:
            await insert_check(
                conn,
                target_id=target_id,
                checked_at=result["checked_at"],
                status_code=result["status_code"],
                latency_ms=result["latency_ms"],
                is_up=result["is_up"],
                error=result["error"],
            )
        logger.info(
            "Target %s: %s %s ms is_up=%s %s",
            target_id,
            result["status_code"],
            result["latency_ms"],
            result["is_up"],
            result["error"] or "",
        )


async def run_cycle(pool: asyncpg.Pool, client: httpx.AsyncClient) -> None:
    """Fetch all targets and check them concurrently (bounded by CHECK_CONCURRENCY)."""
    async with pool.acquire() as conn:
        targets = await get_targets(conn)
    if not targets:
        logger.debug("No targets to check")
        return
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    await asyncio.gather(
        *(check_one(pool, client, semaphore, row["id"], row["url"]) for row in targets)
    )


async def main() -> None:
    logger.info(
        "Worker starting (interval=%ss, timeout=%ss, concurrency=%s)",
        settings.CHECK_INTERVAL_SECONDS,
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
                await asyncio.sleep(settings.CHECK_INTERVAL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
