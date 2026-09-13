"""Add alert-preference columns to users.

Two global boolean toggles (downtime alerts, cert-expiry alerts) — plain columns on `users`
rather than a separate preferences table, since there are only two of them and they're
per-user, not per-target. This is UI-only groundwork for the /settings page (prompt 3.7): no
email-sending logic reads these yet, that's Phase 4's Resend integration.

Revision ID: 007
Revises: 006
Create Date: Add users alert preference columns

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS alert_on_downtime BOOLEAN NOT NULL DEFAULT true"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS alert_on_cert_expiry BOOLEAN NOT NULL DEFAULT true"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS alert_on_cert_expiry"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS alert_on_downtime"))
