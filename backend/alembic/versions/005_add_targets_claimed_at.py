"""Add claimed_at to targets, for concurrency-safe row-claiming during scheduling.

Lets the worker's claim-then-release-then-recheck pattern (SELECT ... FOR UPDATE SKIP LOCKED,
stamp claimed_at, commit immediately) mark a due target as "currently being worked" so a second
concurrent worker instance's own due-target query skips it instead of picking it up too. NULL
means unclaimed; a non-null claimed_at older than the worker's claim TTL is treated as stale
(the worker that claimed it crashed mid-check) and becomes claimable again — see worker/main.py's
CLAIM_TTL_SECONDS.

Revision ID: 005
Revises: 004
Create Date: Add targets claimed_at column

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE")
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS claimed_at"))
