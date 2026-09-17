"""Add webhooks: user-owned alert-delivery endpoints, independent of email (Phase 6, prompt 6.6).

A user can have several webhooks, each independently scoped to downtime and/or cert-expiry
alerts via its own alert_on_downtime/alert_on_cert_expiry toggles (same shape as `users`'
existing email preference columns — see migration 007) plus a global `enabled` kill switch.
`secret` is a server-generated random value used to HMAC-sign outgoing webhook payloads (see
backend/webhooks.py) — stored plaintext, not Fernet-encrypted like a target's basic-auth
password: unlike that credential (which authenticates INTO a third-party system the user
doesn't control), this secret only ever authenticates payloads THIS app sends OUT to the
user's own endpoint, a materially lower-severity exposure if the database were ever
compromised. Revisit if stronger at-rest protection for it is ever wanted.

Revision ID: 013
Revises: 012
Create Date: Add webhooks table

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=False),
        sa.Column("alert_on_downtime", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("alert_on_cert_expiry", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhooks_user_id", "webhooks", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_webhooks_user_id", table_name="webhooks")
    op.drop_table("webhooks")
