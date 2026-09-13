"""Add alert_history: per-(target, region, alert_type) email-alert bookkeeping.

One row per (target_id, region, alert_type) tracks the last state actually alerted on and
when, so downtime/cert-expiry alerting (backend/realtime.py, Phase 4) can suppress repeat
sends while a condition persists and rate-limit reminders with a cooldown — see the Phase 4
design report (CLAUDE.md) for the full reasoning behind the schema shape and cooldown values.

Revision ID: 008
Revises: 007
Create Date: Add alert_history table

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=255), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("last_state", sa.String(length=32), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_cert_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id", "region", "alert_type", name="uq_alert_history_target_region_type"
        ),
    )


def downgrade() -> None:
    op.drop_table("alert_history")
