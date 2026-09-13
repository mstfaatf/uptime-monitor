"""Target model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.check import Check
    from models.user import User


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Worker scheduling state — see backend/alembic/versions/003_add_targets_scheduling_columns.py.
    # next_check_at defaults to now() so a newly created target is due for a check immediately.
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Row-claiming for concurrency-safe scheduling across worker instances — see
    # backend/alembic/versions/005_add_targets_claimed_at.py and worker/main.py's
    # claim_due_targets()/CLAIM_TTL_SECONDS. NULL means unclaimed.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "normalized_url", name="uq_targets_user_id_normalized_url"),)

    user: Mapped["User"] = relationship("User", back_populates="targets")
    checks: Mapped[list["Check"]] = relationship(
        "Check", back_populates="target", cascade="all, delete-orphan", order_by="Check.checked_at.desc()"
    )
