"""Auth endpoints: register, login, logout, me, password reset."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, hash_password, verify_password, create_session_cookie, clear_session_cookie
from config import settings
from database import get_db
from mail import password_reset_email, send_email
from models import PasswordResetToken, User
from rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# How long a password-reset link stays valid. Also used as the "expires in N minutes" figure
# in the email itself, so the two can never drift apart.
RESET_TOKEN_EXPIRY_MINUTES = 60


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    alert_on_downtime: bool
    alert_on_cert_expiry: bool

    class Config:
        from_attributes = True


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class PreferencesUpdateBody(BaseModel):
    alert_on_downtime: bool | None = None
    alert_on_cert_expiry: bool | None = None


class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str


def _hash_reset_token(token: str) -> str:
    """SHA-256, not argon2: the token is a 32-byte cryptographically random value with no
    dictionary to defend against, unlike a human-chosen password — a fast hash is the correct
    tool here, and using argon2 would just make every lookup needlessly slow. See migration
    009's docstring for the full reasoning."""
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register", response_model=UserResponse)
@limiter.limit("3/minute")
async def register(
    request: Request,
    body: RegisterBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create a new user. Returns user and sets HTTP-only session cookie."""
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    create_session_cookie(response, user.id, user.email)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=UserResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and set HTTP-only session cookie."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    create_session_cookie(response, user.id, user.email)
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie."""
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return current authenticated user."""
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password. Requires the current password — same
    401-on-bad-credentials shape as /auth/login, not a distinct error type, so this endpoint
    can't be used to probe whether a password guess is close. Rate-limited for the same reason
    login is: repeated current-password guessing."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    current_user.password_hash = hash_password(body.new_password)
    await db.flush()
    return {"ok": True}


@router.patch("/preferences", response_model=UserResponse)
async def update_preferences(
    body: PreferencesUpdateBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update alert-preference toggles. UI-only groundwork for Phase 4's alerting — nothing
    reads these fields to actually send an email yet. Only the fields present in the request
    body are changed; omitted fields keep their current value."""
    if body.alert_on_downtime is not None:
        current_user.alert_on_downtime = body.alert_on_downtime
    if body.alert_on_cert_expiry is not None:
        current_user.alert_on_cert_expiry = body.alert_on_cert_expiry
    await db.flush()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete the authenticated user's account and everything scoped to it.

    targets.user_id, checks.target_id, and target_region_schedule.target_id are all declared
    ON DELETE CASCADE (see alembic/versions/001_initial_users_targets_checks.py and
    .../006_add_region_and_target_schedule.py), so a single DELETE on the user row cascades
    through targets -> checks and targets -> target_region_schedule at the database level —
    no explicit per-table cleanup needed here. current_user comes from get_current_user, which
    resolves strictly from the caller's own session cookie, so this can only ever delete the
    caller's own row and everything that transitively references it — never another user's.
    """
    await db.delete(current_user)
    clear_session_cookie(response)
    return None


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordBody,
    db: AsyncSession = Depends(get_db),
):
    """Always returns the same generic response whether or not the account exists —
    anti-enumeration, the same reasoning /auth/change-password's 401 shape already relies on
    (a response shouldn't reveal information an attacker couldn't otherwise get). If the
    account exists, generates a reset token, stores its hash, and emails the raw token as a
    link — the raw token itself is never persisted anywhere, only its hash."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is not None:
        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=expires_at,
            )
        )
        await db.flush()
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        subject, body_text = password_reset_email(reset_url=reset_url, expires_in_minutes=RESET_TOKEN_EXPIRY_MINUTES)
        sent = await send_email(user.email, subject, body_text)
        if not sent:
            # Same "log it, don't crash the request, don't pretend it sent" pattern as
            # realtime.py's alert evaluators. The token itself is still created either way —
            # token issuance and email delivery are deliberately separate concerns (see the
            # docstring above) — this only adds visibility for when the send itself fails.
            # The response below stays the same generic message regardless, for
            # anti-enumeration; a failed send must never be observable to the caller.
            logger.warning("Password reset email failed to send for user_id=%s", user.id)
    return {"detail": "If that email is registered, a password reset link has been sent."}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordBody,
    db: AsyncSession = Depends(get_db),
):
    """Consume a reset token: verify it's unexpired and unused, set the new password, mark
    this token used, and invalidate every other outstanding token for the same user (defense
    in depth — an earlier, still-unused reset email shouldn't remain usable after a successful
    reset via a later one).

    Known, accepted limitation: this app's sessions are stateless JWTs with no server-side
    revocation list, so a password reset does not invalidate any other already-logged-in
    session for this user. Not fixed here — flagged, not silently ignored.
    """
    token_hash = _hash_reset_token(body.token)
    result = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    reset_token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired."
        )

    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        # The account was deleted after this token was issued — it's now orphaned.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired."
        )

    user.password_hash = hash_password(body.new_password)
    reset_token.used_at = now

    others = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.id != reset_token.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    for other in others.scalars():
        other.used_at = now

    await db.flush()
    return {"ok": True}