"""Add tags and target_tags: user-owned labels a target can carry, many-to-many.

tags(id, user_id, name, created_at) — ownership is direct via user_id, UNIQUE(user_id, name)
(the same tag name can exist for two different users; not globally unique). target_tags is a
pure join table (no columns beyond the composite primary key) between targets and tags — a
target can carry several tags, a tag can be attached to several targets. Both FKs cascade:
deleting a target or a tag removes the corresponding target_tags rows automatically, no
explicit cleanup needed anywhere.

Revision ID: 012
Revises: 011
Create Date: Add tags and target_tags tables

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_id_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"], unique=False)

    op.create_table(
        "target_tags",
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("target_id", "tag_id"),
    )
    # Supports the reverse lookup ("which targets have tag X") the ?tag= filter on GET /targets
    # needs — the composite PK above already covers "which tags does target X have" via its
    # leading target_id column.
    op.create_index("ix_target_tags_tag_id", "target_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_target_tags_tag_id", table_name="target_tags")
    op.drop_table("target_tags")
    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_table("tags")
