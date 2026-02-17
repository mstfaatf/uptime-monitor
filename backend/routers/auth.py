"""Auth endpoints: register, login, logout, me."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, hash_password, verify_password, create_session_cookie, clear_session_cookie
from database import get_db
from models import User

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

    class Config:
        from_attributes = True


@router.post("/register", response_model=UserResponse)
async def register(
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
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
async def login(
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
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout")
async def logout(response: Response):
    """Clear session cookie."""
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return current authenticated user."""
    return UserResponse(id=current_user.id, email=current_user.email)