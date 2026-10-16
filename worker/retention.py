"""Checks-table retention: prunes raw check rows older than CHECKS_RETENTION_DAYS. Plain delete,
no rollup/aggregate table; that's a clean additive follow-up if long-term trend data (SLA/
heatmap history beyond the retention window) ever turns out to matter.

Called by scheduler.py once per UTC day, on its first claim pass after midnight (in idle mode,
the 00:00 burst), so it never needs a wake-up of its own and holds no connection between runs.

Idempotent by construction: `DELETE FROM checks WHERE checked_at < cutoff` deletes whatever's
still older than the cutoff and is a no-op once nothing is. Both worker regions run this
independently and redundantly; one region's DELETE landing a moment before the other's identical
DELETE just means the second one affects zero rows. No "primary region" coordination is needed.

Row claiming is unaffected: this DELETE only touches the `checks` table, never `targets` or
`target_region_schedule`, the two tables claim_due_targets()'s FOR UPDATE ... SKIP LOCKED and
reschedule_target()'s UPDATE lock, so there is no row-level contention with checking.
"""

from datetime import datetime, timedelta, timezone

import asyncpg


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
