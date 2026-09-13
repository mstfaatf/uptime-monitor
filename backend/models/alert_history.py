"""AlertHistory model — per-(target, region, alert_type) email-alert bookkeeping (Phase 4).

Unlike target_region_schedule (worker-owned, raw asyncpg), this table is owned entirely by
the backend: alerting logic runs in backend/realtime.py's NOTIFY handler, not the worker (see
the Phase 4 design report — the worker stays "just checks and records"), so this is a normal
SQLAlchemy ORM model read/written via the async session, matching every other backend-owned
table.

One row per (target_id, region, alert_type) tracks the last state that was actually alerted on
and when, so a repeat check of the same failing/expiring condition doesn't re-send every time —
see backend/realtime.py's _evaluate_downtime_alert/_evaluate_cert_expiry_alert for the full
suppression + cooldown logic.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.target import Target


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'downtime' | 'cert_expiry'
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # 'down'/'up' for downtime rows; 'expiring' for cert_expiry rows (cert_expiry has no
    # "resolved" concept to track the way downtime has an "up" recovery state).
    last_state: Mapped[str] = mapped_column(String(32), nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # cert_expiry rows only: the exact tls_cert_expires_at this row's alert was about, so a
    # renewal (a new, different expiry timestamp on a later check) is trivially detectable and
    # resets alerting eligibility for the new cert's own expiry window.
    last_cert_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("target_id", "region", "alert_type", name="uq_alert_history_target_region_type"),)

    target: Mapped["Target"] = relationship("Target")
