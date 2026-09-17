"""Add api_keys: user-owned Bearer tokens for programmatic API access (Phase 6, prompt 6.7).

key_hash is a SHA-256 hex digest of the raw key, never the raw key itself — same pattern as
password_reset_tokens (migration 009): a 32-byte cryptographically random value has no
dictionary to defend against, so a fast hash is the correct tool, not argon2. key_prefix (the
raw key's first 12 characters, unhashed) lets a key-list UI distinguish a user's keys from each
other without ever being able to reconstruct the full value from it alone.

scope defaults to 'read' (see backend/auth/api_key.py for what 'read' vs 'full' actually
permits). revoked_at is a soft-delete marker — DELETE /api-keys/{id} sets it rather than
removing the row, so a revoked key's existence and revocation time stay visible for audit
purposes, the same soft-delete shape password_reset_tokens' used_at already established.

Revision ID: 014
Revises: 013
Create Date: Add api_keys table

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
