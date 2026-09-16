"""TargetRegionSchedule model — per-target-per-region worker scheduling state.

Introduced in backend/alembic/versions/006_add_region_and_target_schedule.py to replace the
single, global next_check_at/consecutive_failures/claimed_at that used to live directly on
Target: each checking region's worker instance now tracks its own due-time and backoff/claim
state for a given target independently, since reachability/backoff in one region says nothing
about another.

Written and read exclusively by the worker via raw asyncpg SQL (see worker/main.py) — this
model exists so the table is represented in Base.metadata for Alembic autogenerate parity, not
because the FastAPI backend queries it today. **One deliberate exception** (Phase 6, prompt
6.3): `POST /targets/{id}/resume` (backend/routers/targets.py) writes `next_check_at = now()`
directly to this table, across every region, so resuming a paused target doesn't have to wait
out a stale/future next_check_at — narrow and explicitly noted at its one call site, not a
general loosening of the worker-only-write rule above.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.target import Target


class TargetRegionSchedule(Base):
    __tablename__ = "target_region_schedule"

    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Row-claiming for concurrency-safe scheduling across worker instances within the same
    # region — see worker/main.py's claim_due_targets()/CLAIM_TTL_SECONDS. NULL == unclaimed.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("target_id", "region"),
        Index("ix_target_region_schedule_region_next_check_at", "region", "next_check_at"),
    )

    target: Mapped["Target"] = relationship("Target", back_populates="region_schedules")
