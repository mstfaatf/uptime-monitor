"""User model."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Alert-preference toggles (see alembic/versions/007_*) — UI-only for now, per prompt 3.7;
    # nothing reads these to actually send an email yet, that's Phase 4's Resend integration.
    alert_on_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    alert_on_cert_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    targets: Mapped[list["Target"]] = relationship("Target", back_populates="user", cascade="all, delete-orphan")
