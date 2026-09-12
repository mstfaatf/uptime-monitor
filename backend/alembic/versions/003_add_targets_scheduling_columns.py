"""Add per-target scheduling columns to targets: next_check_at, consecutive_failures.

Used by the worker to schedule each target independently (instead of checking every target
every cycle) and to back off retry frequency after consecutive failures.

Revision ID: 003
Revises: 002
Create Date: Add targets scheduling columns

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Default now(): existing targets are immediately due for a check on the first cycle
    # after this migration runs, same as the old "check everyone every cycle" behavior.
    op.execute(
        sa.text(
            "ALTER TABLE targets ADD COLUMN IF NOT EXISTS next_check_at "
            "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE targets ADD COLUMN IF NOT EXISTS consecutive_failures "
            "INTEGER NOT NULL DEFAULT 0"
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_targets_next_check_at ON targets (next_check_at)"))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_targets_next_check_at"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS consecutive_failures"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS next_check_at"))
