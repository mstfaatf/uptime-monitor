"""Auth endpoints: register, login, logout, me."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, hash_password, verify_password, create_session_cookie, clear_session_cookie
from database import get_db
from models import User
from rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


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