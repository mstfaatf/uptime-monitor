"""Check model (result of a single uptime check)."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.target import Target


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # DNS/TCP/TLS/TTFB timing breakdown (see backend/alembic/versions/004_*). All nullable:
    # a check that failed before reaching a given phase has no timing for it.
    dns_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tcp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tls_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # TLS certificate info, https:// targets only. days-remaining is intentionally NOT
    # stored — derive it at read time (expires_at - now()) so it can't go stale.
    tls_cert_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tls_cert_issuer: Mapped[str | None] = mapped_column(Text, nullable=True)

    target: Mapped["Target"] = relationship("Target", back_populates="checks")

    __table_args__ = (
        Index("ix_checks_target_id_checked_at", "target_id", "checked_at", postgresql_ops={"checked_at": "DESC"}),
    )
