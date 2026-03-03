"""Add normalized_url to targets and unique (user_id, normalized_url).

Revision ID: 002
Revises: 001
Create Date: Add normalized_url

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column if not present (idempotent for re-runs after partial failure)
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS normalized_url VARCHAR(2048)"))
    op.execute(
        sa.text(
            """
            UPDATE targets SET normalized_url = CASE
                WHEN RTRIM(TRIM(url), '/') = '' OR RTRIM(TRIM(url), '/') IS NULL THEN TRIM(url)
                ELSE RTRIM(TRIM(url), '/')
            END
            WHERE normalized_url IS NULL
            """
        )
    )
    op.alter_column(
        "targets",
        "normalized_url",
        existing_type=sa.String(length=2048),
        nullable=False,
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_targets_normalized_url ON targets (normalized_url)"))
    # Remove duplicates: keep the row with the smallest id per (user_id, normalized_url)
    op.execute(
        sa.text(
            """
            DELETE FROM targets t1
            WHERE EXISTS (
                SELECT 1 FROM targets t2
                WHERE t2.user_id = t1.user_id
                  AND t2.normalized_url = t1.normalized_url
                  AND t2.id < t1.id
            )
            """
        )
    )
    # Add unique constraint only if it does not exist (idempotent)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_targets_user_id_normalized_url'
                ) THEN
                    ALTER TABLE targets
                    ADD CONSTRAINT uq_targets_user_id_normalized_url
                    UNIQUE (user_id, normalized_url);
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets DROP CONSTRAINT IF EXISTS uq_targets_user_id_normalized_url"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_targets_normalized_url"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS normalized_url"))
