"""Tag model — user-owned labels a target can carry, many-to-many via target_tags (Phase 6,
prompt 6.4: the multi-tag shape, not a single group_id — a target can carry several labels).

Ownership is enforced directly through Tag.user_id, the same way every other user-owned table
in this app is (CLAUDE.md rule 1) — every tag endpoint filters on it exactly like every target
endpoint filters on Target.user_id. A tag can only ever be attached to a target belonging to
the same user (enforced at attach time in routers/targets.py), so there's no scenario where a
target's tags list could contain a tag owned by someone else.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.target_tag import target_tags

if TYPE_CHECKING:
    from models.target import Target
    from models.user import User


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_id_name"),)

    user: Mapped["User"] = relationship("User")
    targets: Mapped[list["Target"]] = relationship("Target", secondary=target_tags, back_populates="tags")
