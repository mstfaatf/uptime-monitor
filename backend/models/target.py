"""Target model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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

    # Request customization (Phase 6, prompt 6.2) — see
    # backend/alembic/versions/010_add_target_request_customization.py. All nullable: NULL
    # request_method preserves the worker's original HEAD-then-GET-on-failure default; every
    # other field is simply "not configured" when null. basic_auth_password_encrypted is
    # Fernet ciphertext (backend/security/crypto.py) — never the plaintext password, and never
    # returned in any API response.
    request_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    request_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    basic_auth_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basic_auth_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_match: Mapped[str | None] = mapped_column(String(500), nullable=True)
    keyword_match_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="contains")

    # Pause/resume + configurable interval (Phase 6, prompt 6.3) — see
    # backend/alembic/versions/011_add_targets_pause_and_interval.py. paused=true excludes this
    # target from the worker's claim query entirely (see worker/main.py's claim_due_targets),
    # regardless of region. check_interval_seconds=NULL means "use the worker's global
    # CHECK_INTERVAL_SECONDS default" (see reschedule_target's success branch) — preserves
    # today's behavior for every target that hasn't set a custom interval.
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    check_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
