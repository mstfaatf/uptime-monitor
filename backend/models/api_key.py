"""ApiKey model — user-owned Bearer tokens for programmatic API access (Phase 6, prompt 6.7).
Ownership is direct via user_id, same as every other user-owned table (CLAUDE.md rule 1).

key_hash is a SHA-256 hex digest of the raw key, never the raw key itself — same pattern as
PasswordResetToken.token_hash (see that model's docstring for why a fast hash, not argon2, is
correct here). key_prefix (the raw key's first 12 characters, unhashed — see
backend/routers/api_keys.py) lets a key-list UI show enough of a key to distinguish it from a
user's other keys, without that alone being enough to reconstruct the full value — the same
partial-visibility convention GitHub/Stripe use for their own API keys.

scope is 'read' or 'full' — see backend/auth/api_key.py's SCOPE_LEVELS for exactly what each
permits. revoked_at (nullable) is a soft-delete: DELETE /api-keys/{id} sets it rather than
removing the row, preserving a visible record of keys that existed and when they stopped
working, the same soft-delete shape PasswordResetToken.used_at already established.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.user import User


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, server_default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User")
