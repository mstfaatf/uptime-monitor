"""Worker: per-target scheduled HTTP checks, results stored in checks table.

Each target has its own next_check_at; a cycle only checks targets that are currently due,
rather than checking every target on every cycle. A successful check reschedules the target at
the normal cadence (CHECK_INTERVAL_SECONDS); a failed check backs off (see backoff.py) so a
persistently-down target isn't retried on the same tight schedule as a healthy one.

Row-claiming: get_due_targets alone (a bare SELECT) would let two concurrent worker instances
both select and check the same due target, racing on the reschedule write. claim_due_targets()
closes that gap with a claim-then-release-then-recheck pattern: a short transaction does
SELECT ... FOR UPDATE SKIP LOCKED against due, unclaimed-or-stale-claimed targets, stamps
claimed_at = now() on whatever it selected, and commits immediately — releasing the row lock
before the actual HTTP check (which can take several seconds) ever starts, so a lock is never
held for network I/O. A single worker instance sees this as a no-op: it always gets every due
target back, just via two quick transactions instead of one bare SELECT.
"""

import asyncio
import logging
import time
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

# Postgres NOTIFY channel used to tell the backend a check just landed, for its SSE push to
# connected dashboards (backend/realtime.py). Must match that module's NOTIFY_CHANNEL exactly
# — the two services are deployed independently, so this is kept in sync by hand, the same
# "deliberately duplicated, not shared" tradeoff as worker/ssrf.py vs backend/security/ssrf.py.
NOTIFY_CHANNEL = "checks_inserted"

# How long a claim on a target is honored before it's considered stale (the worker that
# claimed it crashed or was killed mid-check) and becomes claimable again. Chosen well above
# the worst realistic single-check duration: up to MAX_REDIRECTS (5) hops, each capped at
# HTTP_TIMEOUT_SECONDS (default 10s) for connect+TLS+request+response, is ~50s in a
# pathological case, plus trivial DB overhead. 120s leaves more than 2x headroom above that
# before assuming a claim was abandoned — long enough that a genuinely slow-but-alive check
# is never falsely reclaimed and double-checked, short enough that a crashed worker's targets
# self-heal well within the normal CHECK_INTERVAL_SECONDS (300s) cadence rather than staying
# stuck until a manual fix.
CLAIM_TTL_SECONDS = 120


async def claim_due_targets(conn: asyncpg.Connection) -> list[dict]:
    """
    Select targets currently due for a check and claim them, atomically, so a concurrent
    worker instance's own call to this function can never come back with the same target.

    SELECT ... FOR UPDATE SKIP LOCKED means a genuinely concurrent claim attempt on the same
    row doesn't block waiting for this transaction — it just skips that row and returns
    whatever else is due. The row lock is only held long enough to stamp claimed_at and
    commit; the caller does the actual HTTP check afterward, outside any transaction.

    A target is "due" if its schedule says so AND it isn't currently claimed by a still-live
    claim: claimed_at is either NULL (never claimed / already cleared after a prior check) or
    older than CLAIM_TTL_SECONDS (stale — treat as abandoned).
    """
    async with conn.transaction():
        rows = await conn.fetch(
            """
            SELECT id, url, consecutive_failures
            FROM targets
            WHERE next_check_at <= now()
              AND (claimed_at IS NULL OR claimed_at < now() - make_interval(secs => $1))
            FOR UPDATE SKIP LOCKED
            """,
            CLAIM_TTL_SECONDS,
        )
        if rows:
            await conn.execute(
                "UPDATE targets SET claimed_at = now() WHERE id = ANY($1::int[])",
                [row["id"] for row in rows],
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
    dns_ms: int | None,
    tcp_ms: int | None,
    tls_ms: int | None,
    ttfb_ms: int | None,
    tls_cert_expires_at: datetime | None,
    tls_cert_issuer: str | None,
) -> None:
    """Insert one row into checks — the honest historical record of this attempt, written
    unconditionally regardless of how the target gets rescheduled afterwards."""
    await conn.execute(
        """
        INSERT INTO checks (
            target_id, checked_at, status_code, latency_ms, is_up, error,
            dns_ms, tcp_ms, tls_ms, ttfb_ms, tls_cert_expires_at, tls_cert_issuer
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
        target_id,
        checked_at,
        status_code,
        latency_ms,
        is_up,
        error or None,
        dns_ms,
        tcp_ms,
        tls_ms,
        ttfb_ms,
        tls_cert_expires_at,
        tls_cert_issuer,
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
    schedules the next attempt using exponential backoff with jitter. Either way, this clears
    claimed_at — the claim's job (keeping another worker instance from grabbing this target
    while it was being checked) is done once this write lands.
    """
    if is_up:
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=settings.CHECK_INTERVAL_SECONDS)
        await conn.execute(
            "UPDATE targets SET consecutive_failures = 0, next_check_at = $2, claimed_at = NULL WHERE id = $1",
            target_id,
            next_check_at,
        )
    else:
        new_failures = consecutive_failures_before + 1
        delay_seconds = compute_backoff_seconds(new_failures)
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        await conn.execute(
            "UPDATE targets SET consecutive_failures = $2, next_check_at = $3, claimed_at = NULL WHERE id = $1",
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
            # Timed so its cost is reported as dns_ms rather than performing a second,
            # redundant DNS lookup just for timing purposes.
            dns_start = time.perf_counter()
            blocked, reason = await asyncio.to_thread(is_url_blocked, url)
            dns_ms = int((time.perf_counter() - dns_start) * 1000)
            if blocked:
                result = {
                    "checked_at": datetime.now(timezone.utc),
                    "status_code": None,
                    "latency_ms": None,
                    "is_up": False,
                    "error": reason,
                    "dns_ms": dns_ms,
                    "tcp_ms": None,
                    "tls_ms": None,
                    "ttfb_ms": None,
                    "tls_cert_expires_at": None,
                    "tls_cert_issuer": None,
                }
                logger.info("Target %s blocked (SSRF): %s", target_id, reason)
            else:
                result = await check_url(client, url, dns_ms)
                logger.info(
                    "Target %s: %s %s ms (dns=%s tcp=%s tls=%s ttfb=%s) is_up=%s %s",
                    target_id,
                    result["status_code"],
                    result["latency_ms"],
                    result["dns_ms"],
                    result["tcp_ms"],
                    result["tls_ms"],
                    result["ttfb_ms"],
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
                    dns_ms=result["dns_ms"],
                    tcp_ms=result["tcp_ms"],
                    tls_ms=result["tls_ms"],
                    ttfb_ms=result["ttfb_ms"],
                    tls_cert_expires_at=result["tls_cert_expires_at"],
                    tls_cert_issuer=result["tls_cert_issuer"],
                )
                await reschedule_target(conn, target_id, result["is_up"], consecutive_failures_before)
                # NOTIFY inside the same transaction: Postgres only actually delivers a
                # notification once its transaction commits, so if the insert/reschedule above
                # gets rolled back (e.g. the FK-violation case caught below), no notification
                # goes out for a check that was never really persisted.
                await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, str(target_id))
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
    """Claim targets currently due for a check and check them concurrently (bounded by
    CHECK_CONCURRENCY) — targets not yet due, or already claimed by another still-live worker,
    are left alone until their next_check_at (or claim) expires."""
    async with pool.acquire() as conn:
        targets = await claim_due_targets(conn)
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
        # max_keepalive_connections=0: force a brand-new TCP+TLS connection for every single
        # request instead of reusing a pooled one. A reused connection would skip the
        # connect_tcp/start_tls trace events entirely, silently leaving tcp_ms/tls_ms null on
        # any check that happens to land on a still-warm connection — unacceptable for a
        # timing breakdown that's supposed to measure real connection-establishment cost on
        # every check, not whatever the pool happened to have lying around.
        async with httpx.AsyncClient(
            timeout=settings.HTTP_TIMEOUT_SECONDS,
            verify=settings.HTTP_VERIFY_SSL,
            limits=httpx.Limits(max_keepalive_connections=0),
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
