"""Worker: per-target scheduled HTTP checks, results stored in checks table.

Scheduling state (next_check_at, consecutive_failures, claimed_at) lives in
target_region_schedule, one row per (target_id, region) — see
backend/alembic/versions/006_add_region_and_target_schedule.py. This worker instance only
ever reads/writes rows for its own settings.REGION: each checking region tracks its own
due-time and backoff/claim state for a target independently, since reachability/backoff in one
region says nothing about another. A successful check reschedules the target at the normal
cadence — CHECK_INTERVAL_SECONDS globally, or a target's own check_interval_seconds when it has
one configured (Phase 6, prompt 6.3); a failed check backs off (see backoff.py) regardless of
that custom interval, so a persistently-down target isn't retried on its own tight schedule any
more than a healthy one would be. A paused target (targets.paused) is excluded from
claim_due_targets' WHERE clause entirely — it's never selected, never checked, until resumed.

Row-claiming: a bare SELECT of due rows would let two concurrent worker instances *in the same
region* both select and check the same due target, racing on the reschedule write.
claim_due_targets() closes that gap with a claim-then-release-then-recheck pattern: a short
transaction does SELECT ... FOR UPDATE SKIP LOCKED against this region's due,
unclaimed-or-stale-claimed schedule rows, stamps claimed_at = now() on whatever it selected,
and commits immediately — releasing the row lock before the actual HTTP check (which can take
several seconds) ever starts, so a lock is never held for network I/O. A single worker instance
sees this as a no-op: it always gets every due target back, just via two quick transactions
instead of one bare SELECT. Two instances in *different* regions never contend for the same
row at all, since each only ever queries its own region's rows.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx

from backoff import compute_backoff_seconds
from config import settings
from checker import check_url
from crypto import decrypt_secret
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
# connected dashboards (backend/realtime.py). The payload sent on this channel is
# "{target_id}:{region}" (see check_one below) — both the channel name and that payload format
# must match backend/realtime.py's parsing exactly. The two services are deployed
# independently, so this is kept in sync by hand, the same "deliberately duplicated, not
# shared" tradeoff as worker/ssrf.py vs backend/security/ssrf.py.
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


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Teach every pooled connection how to (de)serialize jsonb columns as plain Python
    dicts. asyncpg doesn't do this automatically outside SQLAlchemy's engine — this is the
    first jsonb column (targets.request_headers, Phase 6 prompt 6.2) this raw-asyncpg codepath
    has ever needed to read. Registered via asyncpg.create_pool's `init` hook (see main()), so
    it applies to every connection the pool ever hands out, not just one."""
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text")


async def ensure_schedule_rows(conn: asyncpg.Connection, region: str) -> None:
    """
    Guarantee every target has a target_region_schedule row for this region, before claiming.

    A target can exist with no schedule row for this region in two cases: it was created (by
    the API, POST /targets) after this worker last ran this check, or this is the first time a
    worker for this region has ever seen a pre-existing target (e.g. a brand-new region being
    added). The API doesn't know what regions exist — REGION is a worker-only identity, not
    shared/stored anywhere as a canonical list — so schedule rows are backfilled lazily here
    instead of at target-creation time. New rows are due immediately (next_check_at = now()),
    matching targets.next_check_at's old server_default behavior of checking a new target right
    away. ON CONFLICT DO NOTHING makes this safe under concurrent same-region workers racing to
    backfill the same missing row.
    """
    await conn.execute(
        """
        INSERT INTO target_region_schedule (target_id, region, next_check_at, consecutive_failures)
        SELECT t.id, $1, now(), 0
        FROM targets t
        LEFT JOIN target_region_schedule trs ON trs.target_id = t.id AND trs.region = $1
        WHERE trs.target_id IS NULL
        ON CONFLICT (target_id, region) DO NOTHING
        """,
        region,
    )


async def claim_due_targets(conn: asyncpg.Connection, region: str) -> list[dict]:
    """
    Select this region's targets currently due for a check and claim them, atomically, so a
    concurrent worker instance in the same region can never come back with the same target.
    (A worker in a different region never contends here at all — the WHERE region = $1 means
    the two never even look at the same rows.)

    SELECT ... FOR UPDATE OF trs SKIP LOCKED means a genuinely concurrent claim attempt on the
    same row doesn't block waiting for this transaction — it just skips that row and returns
    whatever else is due. "OF trs" scopes the lock to target_region_schedule rows only, not the
    joined targets rows (no reason to contend with, say, a delete on targets). The row lock is
    only held long enough to stamp claimed_at and commit; the caller does the actual HTTP check
    afterward, outside any transaction.

    A schedule row is "due" if its next_check_at says so AND it isn't currently claimed by a
    still-live claim: claimed_at is either NULL (never claimed / already cleared after a prior
    check) or older than CLAIM_TTL_SECONDS (stale — treat as abandoned).

    Also selects each target's request-customization fields (Phase 6, prompt 6.2:
    request_method/request_headers/basic_auth_*/keyword_match*) and its pause/interval fields
    (Phase 6, prompt 6.3: check_interval_seconds — paused targets are excluded by the WHERE
    clause below, not selected at all) so check_one has everything it needs for this check
    without a second query — these are per-target, not per-region, so they come straight off
    `targets`, not the schedule table.
    """
    await ensure_schedule_rows(conn, region)

    async with conn.transaction():
        rows = await conn.fetch(
            """
            SELECT t.id, t.url, trs.consecutive_failures,
                   t.request_method, t.request_headers, t.basic_auth_username,
                   t.basic_auth_password_encrypted, t.keyword_match, t.keyword_match_mode,
                   t.check_interval_seconds
            FROM target_region_schedule trs
            JOIN targets t ON t.id = trs.target_id
            WHERE trs.region = $1
              AND NOT t.paused
              AND trs.next_check_at <= now()
              AND (trs.claimed_at IS NULL OR trs.claimed_at < now() - make_interval(secs => $2))
            FOR UPDATE OF trs SKIP LOCKED
            """,
            region,
            CLAIM_TTL_SECONDS,
        )
        if rows:
            await conn.execute(
                "UPDATE target_region_schedule SET claimed_at = now() WHERE region = $1 AND target_id = ANY($2::int[])",
                region,
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
    region: str,
) -> None:
    """Insert one row into checks — the honest historical record of this attempt, written
    unconditionally regardless of how the target gets rescheduled afterwards. Tagged with the
    region that performed it — backoff/claiming affects scheduling only, never whether or how
    an actual check result gets recorded."""
    await conn.execute(
        """
        INSERT INTO checks (
            target_id, checked_at, status_code, latency_ms, is_up, error,
            dns_ms, tcp_ms, tls_ms, ttfb_ms, tls_cert_expires_at, tls_cert_issuer, region
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
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
        region,
    )


async def reschedule_target(
    conn: asyncpg.Connection,
    target_id: int,
    region: str,
    is_up: bool,
    consecutive_failures_before: int,
    check_interval_seconds: int | None = None,
) -> None:
    """
    Update this (target_id, region)'s scheduling state after a check. Success resets the
    failure streak and returns to the normal cadence — the target's own check_interval_seconds
    (Phase 6, prompt 6.3) if it has one configured, else the worker's global
    CHECK_INTERVAL_SECONDS default; failure increments the streak and schedules the next
    attempt using exponential backoff with jitter regardless of check_interval_seconds (a
    failing target should back off, not retry on its custom fast cadence). Either way, this
    clears claimed_at — the claim's job (keeping another worker instance in this same region
    from grabbing this target while it was being checked) is done once this write lands.
    """
    if is_up:
        interval = check_interval_seconds or settings.CHECK_INTERVAL_SECONDS
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=interval)
        await conn.execute(
            "UPDATE target_region_schedule SET consecutive_failures = 0, next_check_at = $3, claimed_at = NULL "
            "WHERE target_id = $1 AND region = $2",
            target_id,
            region,
            next_check_at,
        )
    else:
        new_failures = consecutive_failures_before + 1
        delay_seconds = compute_backoff_seconds(new_failures)
        next_check_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        await conn.execute(
            "UPDATE target_region_schedule SET consecutive_failures = $3, next_check_at = $4, claimed_at = NULL "
            "WHERE target_id = $1 AND region = $2",
            target_id,
            region,
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
    region: str,
    request_method: str | None,
    request_headers: dict | None,
    basic_auth_username: str | None,
    basic_auth_password_encrypted: str | None,
    keyword_match: str | None,
    keyword_match_mode: str,
    check_interval_seconds: int | None,
) -> None:
    """Check a single target, bounded by the semaphore, record its result, and reschedule it.
    request_method/request_headers/basic_auth_*/keyword_match* are this target's optional
    request-customization fields (Phase 6, prompt 6.2), read off `targets` by
    claim_due_targets — None/default means "no customization," behaving exactly as before this
    feature existed. check_interval_seconds (Phase 6, prompt 6.3) is threaded through to
    reschedule_target's success branch unchanged; paused targets never reach this function at
    all (claim_due_targets excludes them)."""
    async with semaphore:
        auth: httpx.BasicAuth | None = None
        if basic_auth_username and basic_auth_password_encrypted:
            try:
                auth = httpx.BasicAuth(basic_auth_username, decrypt_secret(basic_auth_password_encrypted))
            except Exception:
                # A decrypt failure (most likely: CREDENTIAL_ENCRYPTION_KEY has drifted between
                # the backend and this worker) shouldn't crash the whole check cycle via the
                # broad except below, which would misleadingly log this as "may have been
                # deleted mid-check" — log it distinctly and proceed unauthenticated, which will
                # most likely surface as a normal 401 from the target rather than a check that
                # silently never runs.
                logger.exception(
                    "[region=%s] Failed to decrypt basic-auth credentials for target %s; "
                    "checking without auth",
                    region,
                    target_id,
                )
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
                logger.info("[region=%s] Target %s blocked (SSRF): %s", region, target_id, reason)
            else:
                result = await check_url(
                    client,
                    url,
                    dns_ms,
                    method=request_method,
                    headers=request_headers,
                    auth=auth,
                    keyword_match=keyword_match,
                    keyword_match_mode=keyword_match_mode,
                )
                logger.info(
                    "[region=%s] Target %s: %s %s ms (dns=%s tcp=%s tls=%s ttfb=%s) is_up=%s %s",
                    region,
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
                    region=region,
                )
                await reschedule_target(
                    conn, target_id, region, result["is_up"], consecutive_failures_before, check_interval_seconds
                )
                # NOTIFY inside the same transaction: Postgres only actually delivers a
                # notification once its transaction commits, so if the insert/reschedule above
                # gets rolled back (e.g. the FK-violation case caught below), no notification
                # goes out for a check that was never really persisted. Payload is
                # "{target_id}:{region}" — must match backend/realtime.py's parsing exactly
                # (kept in sync by hand, the two services are deployed independently).
                await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, f"{target_id}:{region}")
        except Exception:
            # A target can be deleted by its owner between being selected for this cycle and
            # this check completing — most concretely, the INSERT above would then violate the
            # checks.target_id foreign key once the target row is gone. Rather than let that
            # (or any other unexpected per-target error) propagate out of asyncio.gather() and
            # cancel every other concurrently in-flight check this cycle, log it and move on:
            # a deleted target simply won't be selected again (its row, and schedule row with
            # it, no longer exists); any other target's state is untouched by this one failing.
            logger.exception(
                "[region=%s] Check failed for target %s (it may have been deleted mid-check)",
                region,
                target_id,
            )


async def run_cycle(pool: asyncpg.Pool, client: httpx.AsyncClient) -> None:
    """Claim this worker's region's targets currently due for a check and check them
    concurrently (bounded by CHECK_CONCURRENCY) — targets not yet due, or already claimed by
    another still-live worker in the same region, are left alone until their next_check_at (or
    claim) expires."""
    region = settings.REGION
    async with pool.acquire() as conn:
        targets = await claim_due_targets(conn, region)
    if not targets:
        logger.debug("[region=%s] No targets due for a check", region)
        return
    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    await asyncio.gather(
        *(
            check_one(
                pool,
                client,
                semaphore,
                row["id"],
                row["url"],
                row["consecutive_failures"],
                region,
                request_method=row["request_method"],
                request_headers=row["request_headers"],
                basic_auth_username=row["basic_auth_username"],
                basic_auth_password_encrypted=row["basic_auth_password_encrypted"],
                keyword_match=row["keyword_match"],
                keyword_match_mode=row["keyword_match_mode"],
                check_interval_seconds=row["check_interval_seconds"],
            )
            for row in targets
        )
    )


async def main() -> None:
    logger.info(
        "Worker starting (region=%s, interval=%ss, tick=%ss, timeout=%ss, concurrency=%s)",
        settings.REGION,
        settings.CHECK_INTERVAL_SECONDS,
        SCHEDULER_TICK_SECONDS,
        settings.HTTP_TIMEOUT_SECONDS,
        CHECK_CONCURRENCY,
    )
    pool = await asyncpg.create_pool(settings.asyncpg_database_url, init=_init_connection)
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
