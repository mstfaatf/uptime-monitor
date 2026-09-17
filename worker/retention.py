"""Checks-table retention (Phase 6, prompt 6.8): prunes raw check rows older than
CHECKS_RETENTION_DAYS. Plain delete for this first pass — no rollup/aggregate table. Per the
6.1 report: that's a clean additive follow-up if long-term trend data (SLA/heatmap history
beyond the retention window) ever turns out to matter, not something to build speculatively
now, since this project's real data volume doesn't need it yet (see the 4.8 export prompt's
own row-count measurements).

Idempotent by construction: `DELETE FROM checks WHERE checked_at < cutoff` deletes whatever's
still older than the cutoff and is a no-op once nothing is. Both worker regions run this
independently and redundantly — one region's DELETE landing a moment before the other's
identical DELETE just means the second one affects zero rows. No new "primary region"
coordination concept is introduced (or wanted — inventing one here, when nothing else in this
system has one, would be solving a problem idempotency already solves for free).

Sequencing relative to row-claiming (Phase 2 — CLAUDE.md's non-negotiable multi-region
coordination rule): this module's DELETE only ever touches the `checks` table. It never reads
or writes `targets` or `target_region_schedule` — the two tables claim_due_targets()'s
`SELECT ... FOR UPDATE OF trs SKIP LOCKED` and reschedule_target()'s UPDATE actually lock —
so there is no row-level contention between this loop and the check-claiming/scheduling path
at all, regardless of timing. The two loops share only the asyncpg connection pool, which is
built for concurrent acquisition by exactly this kind of independent, simultaneous use; this
loop acquires its own connection for the single DELETE statement's duration and releases it
immediately, never holding it across an await boundary that could stall a check cycle. See
run_retention_loop's docstring for how it's scheduled relative to main()'s check-cycle loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from config import settings

logger = logging.getLogger(__name__)

# Deliberately coarse, per the prompt: a background sweep every ~24h, not folded into
# SCHEDULER_TICK_SECONDS (5s) — pruning is a maintenance task with no user-facing latency
# requirement, unlike claiming/checking due targets. A fresh worker process waits one full
# interval before its first sweep rather than pruning immediately at startup, so a routine
# restart/redeploy never triggers a prune burst as a side effect.
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


async def prune_old_checks(pool: asyncpg.Pool, retention_days: int) -> int:
    """Delete checks rows with checked_at older than retention_days ago. Returns the number of
    rows actually deleted (parsed from asyncpg's own "DELETE N" command-status string, purely
    for logging — nothing else depends on the exact count). A single DELETE statement, not
    wrapped in an explicit transaction: one statement is already atomic on its own, and there's
    no second statement here that would need to commit alongside it."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM checks WHERE checked_at < $1", cutoff)
    try:
        return int(status.split()[-1])
    except (IndexError, ValueError):
        return 0


async def run_retention_loop(pool: asyncpg.Pool) -> None:
    """Runs for the life of the process as a second, independent asyncio task started
    alongside main()'s check-cycle loop (see main() — asyncio.create_task, not nested inside
    the existing while-True loop or run_cycle()). The two loops never call into each other and
    share nothing but the connection pool (see module docstring for why that's safe).

    Sleeps first, then prunes, forever — so a routine restart never causes an immediate prune
    burst, and prune sweeps land roughly once a day for as long as the process keeps running. A
    per-sweep failure (logged, not raised) never stops future sweeps or affects the check-cycle
    loop in any way; this task and main()'s check loop fail independently of each other.
    """
    while True:
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)
        try:
            deleted = await prune_old_checks(pool, settings.CHECKS_RETENTION_DAYS)
            if deleted:
                logger.info(
                    "[region=%s] Retention: pruned %d check row(s) older than %d days",
                    settings.REGION,
                    deleted,
                    settings.CHECKS_RETENTION_DAYS,
                )
        except Exception:
            logger.exception("[region=%s] Retention sweep failed", settings.REGION)
