"""Add timing-breakdown and TLS cert columns to checks: dns_ms, tcp_ms, tls_ms, ttfb_ms,
tls_cert_expires_at, tls_cert_issuer.

All nullable: http:// targets never populate the TLS cert columns, and any column can be
null when a check failed before reaching that phase (e.g. a connect timeout has no tls_ms).
days-remaining for cert expiry is deliberately NOT stored here — it's derived at read time
in the API layer (expires_at - now()) so it can't go stale between checks.

Revision ID: 004
Revises: 003
Create Date: Add checks timing + cert columns

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS dns_ms INTEGER"))
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS tcp_ms INTEGER"))
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS tls_ms INTEGER"))
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS ttfb_ms INTEGER"))
    op.execute(
        sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS tls_cert_expires_at TIMESTAMP WITH TIME ZONE")
    )
    op.execute(sa.text("ALTER TABLE checks ADD COLUMN IF NOT EXISTS tls_cert_issuer TEXT"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS tls_cert_issuer"))
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS tls_cert_expires_at"))
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS ttfb_ms"))
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS tls_ms"))
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS tcp_ms"))
    op.execute(sa.text("ALTER TABLE checks DROP COLUMN IF EXISTS dns_ms"))
