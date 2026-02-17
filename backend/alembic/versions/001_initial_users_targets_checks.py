"""Initial schema: users, targets, checks with indexes.

Revision ID: 001
Revises:
Create Date: Initial

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_targets_user_id"), "targets", ["user_id"], unique=False)

    op.create_table(
        "checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("is_up", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_checks_target_id"), "checks", ["target_id"], unique=False)
    op.create_index(op.f("ix_checks_checked_at"), "checks", ["checked_at"], unique=False)
    op.create_index(
        "ix_checks_target_id_checked_at",
        "checks",
        ["target_id", "checked_at"],
        unique=False,
        postgresql_ops={"checked_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_checks_target_id_checked_at", table_name="checks")
    op.drop_index(op.f("ix_checks_checked_at"), table_name="checks")
    op.drop_index(op.f("ix_checks_target_id"), table_name="checks")
    op.drop_table("checks")
    op.drop_index(op.f("ix_targets_user_id"), table_name="targets")
    op.drop_table("targets")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
