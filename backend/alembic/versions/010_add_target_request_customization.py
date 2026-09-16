"""Add request-customization columns to targets: request_method, request_headers,
basic_auth_username, basic_auth_password_encrypted, keyword_match, keyword_match_mode.

All nullable except keyword_match_mode (which defaults to 'contains' so existing rows and any
insert that doesn't specify it behave the same as "no special mode"). request_method=NULL
preserves the worker's original HEAD-then-GET-on-failure default for every existing target —
an explicit value opts a target out of that fallback entirely (see worker/checker.py).
basic_auth_password_encrypted stores Fernet ciphertext (backend/security/crypto.py), never a
plaintext password — see CREDENTIAL_ENCRYPTION_KEY in config.py for the required encryption
key this depends on.

Revision ID: 010
Revises: 009
Create Date: Add target request-customization columns

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS request_method VARCHAR(10)"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS request_headers JSONB"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS basic_auth_username VARCHAR(255)"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS basic_auth_password_encrypted TEXT"))
    op.execute(sa.text("ALTER TABLE targets ADD COLUMN IF NOT EXISTS keyword_match VARCHAR(500)"))
    op.execute(
        sa.text(
            "ALTER TABLE targets ADD COLUMN IF NOT EXISTS keyword_match_mode VARCHAR(20) "
            "NOT NULL DEFAULT 'contains'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS keyword_match_mode"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS keyword_match"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS basic_auth_password_encrypted"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS basic_auth_username"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS request_headers"))
    op.execute(sa.text("ALTER TABLE targets DROP COLUMN IF EXISTS request_method"))
