"""Add pause/resume and configurable check interval to targets: paused, check_interval_seconds.

paused (NOT NULL DEFAULT false): when true, the worker's claim query excludes this target
entirely (see worker/main.py's claim_due_targets) — it is never selected, never checked, until
resumed. check_interval_seconds (nullable): a per-target override of the worker's global
CHECK_INTERVAL_SECONDS, used only on a successful check's reschedule (see
worker/main.py's reschedule_target); NULL means "use the global default," preserving today's
behavior for every existing target.

Revision ID: 011
Revises: 010
Create Date: Add targets pause/resume and check-interval columns

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT false"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS check_interval_seconds INTEGER"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS check_interval_seconds"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS paused"))
