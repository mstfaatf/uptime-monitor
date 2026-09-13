"""Move scheduling state off targets into a per-target-per-region table; add region to checks.

Part of the Phase 2 multi-region design: a target's reachability/backoff state can genuinely
differ per checking region (that's the whole point of checking from multiple regions), so one
shared next_check_at/consecutive_failures/claimed_at on targets doesn't make sense anymore —
each region's worker instance needs to track its own due-time and backoff/claim state for a
given target independently. See the Phase 2 design report (CLAUDE.md) for the full reasoning.

Steps, in order:
  1. Add checks.region (nullable first, backfilled, then set NOT NULL — the standard safe
     pattern for adding a NOT NULL column to a table that already has rows).
  2. Create target_region_schedule(target_id, region, next_check_at, consecutive_failures,
     claimed_at) with a composite primary key on (target_id, region) — a target can have at
     most one schedule row per region, which is also exactly the uniqueness guarantee needed.
  3. Seed one target_region_schedule row per existing target, carrying its current
     next_check_at/consecutive_failures/claimed_at forward exactly (not resetting to "due
     now", which would cause a check storm across every target the moment this migration
     lands) under a single seed region.
  4. A hard gate (a PL/pgSQL DO block that RAISEs and aborts the migration transaction) checks
     that target_region_schedule ended up with exactly one row per existing target before
     proceeding — if the seed step silently missed a target, this migration fails loudly
     instead of silently dropping that target's schedule columns a moment later.
  5. Only once that gate passes: drop next_check_at/consecutive_failures/claimed_at (and their
     index) from targets.

Seed region value: "local" — matches worker/config.py's REGION default (see
backend/alembic/versions before this one added REGION config plumbing to the worker). This
project has only ever run as a single, non-multi-region deployment so far, so every existing
check row and every existing target's schedule state genuinely was produced by "the local
worker instance" — labeling the historical data and the seeded schedule rows with the same
identity the worker itself already reports is the honest, non-arbitrary choice, not a
placeholder that would need to be revisited later.

Known temporary regression, explicitly accepted: worker/main.py's claim_due_targets() and
reschedule_target() still query targets.next_check_at/consecutive_failures/claimed_at directly
— this migration does not touch worker code (out of scope; rewriting the worker to query
target_region_schedule instead is the very next prompt). Once this migration runs, those
columns no longer exist, so every worker cycle's claim query will fail with a real Postgres
error ("column does not exist"). This does NOT crash the worker process: main()'s outer loop
already wraps run_cycle() in a try/except that logs "Cycle failed" and retries after
SCHEDULER_TICK_SECONDS — the exact same self-healing path that already handles the worker
racing the API's migration on a fresh `docker compose up` (see the Phase 1 prompt 1.3 status
notes). The worker will simply perform no checks and log "Cycle failed" every 5s until the
next prompt rewrites its scheduling queries against target_region_schedule.

Revision ID: 006
Revises: 005
Create Date: Add checks.region and target_region_schedule

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_REGION = "local"


def upgrade() -> None:
    # --- 1. checks.region ---
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS region VARCHAR(255)"))
    op.execute(sa.text("UPDATE checks SET region = :seed WHERE region IS NULL").bindparams(seed=SEED_REGION))
    op.execute(sa.text("ALTER TABLE checks ALTER COLUMN region SET NOT NULL"))

    # --- 2. target_region_schedule ---
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS target_region_schedule (
                target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
                region VARCHAR(255) NOT NULL,
                next_check_at TIMESTAMP WITH TIME ZONE NOT NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                claimed_at TIMESTAMP WITH TIME ZONE,
                PRIMARY KEY (target_id, region)
            )
            """
        )
    )
    # Mirrors ix_targets_next_check_at's role on the old column: the due-target query (step 4
    # of the Phase 2 build order, next prompt) will filter by region and next_check_at together.
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_target_region_schedule_region_next_check_at "
            "ON target_region_schedule (region, next_check_at)"
        )
    )

    # --- 3. Seed one row per existing target, carrying its current schedule state forward ---
    op.execute(
        sa.text(
            """
            INSERT INTO target_region_schedule (target_id, region, next_check_at, consecutive_failures, claimed_at)
            SELECT id, :seed, next_check_at, consecutive_failures, claimed_at
            FROM targets
            ON CONFLICT (target_id, region) DO NOTHING
            """
        ).bindparams(seed=SEED_REGION)
    )

    # --- 4. Hard gate: abort rather than silently drop columns if the seed step missed a target ---
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                targets_count integer;
                schedule_count integer;
            BEGIN
                SELECT count(*) INTO targets_count FROM targets;
                SELECT count(*) INTO schedule_count FROM target_region_schedule;
                IF targets_count != schedule_count THEN
                    RAISE EXCEPTION
                        'target_region_schedule seed mismatch: % targets but % schedule rows — aborting before dropping targets scheduling columns',
                        targets_count, schedule_count;
                END IF;
            END $$;
            """
        )
    )

    # --- 5. Only now: drop the old scheduling columns from targets ---
    op.execute(sa.text("DROP INDEX IF EXISTS ix_targets_next_check_at"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS claimed_at"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS consecutive_failures"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS next_check_at"))


def downgrade() -> None:
    # Restore targets' scheduling columns, backfilled from target_region_schedule's seed
    # region — the inverse data movement of upgrade()'s step 3. If more than one region's
    # schedule exists by the time this downgrade runs (i.e. multi-region has since gone live),
    # only the seed region's row survives the collapse back to one row per target; that's an
    # inherent, unavoidable lossy edge of downgrading a one-to-many schema back to one-to-one,
    # not a bug in this migration.
    op.execute(
        sa.text(
            "ALTER TABLE targets ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
        )
    )
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE"))

    op.execute(
        sa.text(
            """
            UPDATE targets
            SET next_check_at = trs.next_check_at,
                consecutive_failures = trs.consecutive_failures,
                claimed_at = trs.claimed_at
            FROM target_region_schedule trs
            WHERE trs.target_id = targets.id AND trs.region = :seed
            """
        ).bindparams(seed=SEED_REGION)
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_targets_next_check_at ON targets (next_check_at)"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_target_region_schedule_region_next_check_at"))
    op.execute(sa.text("DROP TABLE IF EXISTS target_region_schedule"))

    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS region"))
