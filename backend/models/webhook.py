"""Webhook model — user-owned alert-delivery endpoints, independent of email (Phase 6, prompt
6.6). Ownership is direct via user_id, same as every other user-owned table (CLAUDE.md rule 1).

alert_on_downtime/alert_on_cert_expiry mirror users' own email-preference columns (migration
007) — each webhook is scoped to alert types independently, and independently of the owning
user's email preferences: a user can have email downtime alerts off but a webhook for them on,
or vice versa. See backend/realtime.py's fan-out restructuring (prompt 6.6) for how these are
consulted alongside (not instead of) the user's own email toggles.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.user import User


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Server-generated (never user-supplied) — see routers/webhooks.py. Used as the HMAC key
    # signing outgoing payloads (backend/webhooks.py); shown to the caller exactly once, at
    # creation, never returned by any other endpoint.
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    alert_on_downtime: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    alert_on_cert_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # A global kill switch, independent of the two alert-type toggles above — lets a user
    # temporarily silence a webhook (e.g. its receiver is down for maintenance) without losing
    # its per-type configuration.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")
