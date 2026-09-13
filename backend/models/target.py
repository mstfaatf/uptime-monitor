"""Target model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.check import Check
    from models.target_region_schedule import TargetRegionSchedule
    from models.user import User


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Worker scheduling state (next_check_at, consecutive_failures, claimed_at) used to live
    # directly on this table — see backend/alembic/versions/003_add_targets_scheduling_columns.py
    # and .../005_add_targets_claimed_at.py. Moved to models.target_region_schedule.
    # TargetRegionSchedule in backend/alembic/versions/006_add_region_and_target_schedule.py:
    # each checking region now tracks its own due-time/backoff/claim state per target
    # independently, since reachability can genuinely differ by region.

    __table_args__ = (UniqueConstraint("user_id", "normalized_url", name="uq_targets_user_id_normalized_url"),)

    user: Mapped["User"] = relationship("User", back_populates="targets")
    checks: Mapped[list["Check"]] = relationship(
        "Check", back_populates="target", cascade="all, delete-orphan", order_by="Check.checked_at.desc()"
    )
    region_schedules: Mapped[list["TargetRegionSchedule"]] = relationship(
        "TargetRegionSchedule", back_populates="target", cascade="all, delete-orphan"
    )
