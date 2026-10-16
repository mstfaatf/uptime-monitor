"""FastAPI dependencies for authentication."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import activity
from auth.cookies import read_session_token
from config import settings
from database import AsyncSessionLocal, get_db
from models import User


async def _user_from_session_cookie(request: Request, session: AsyncSession) -> User:
    """Resolve the HTTP-only session cookie to a User using the given session, or raise 401.
    Shared by get_current_user (request-scoped session) and get_current_user_id_short_lived
    (a session that closes before the caller continues)."""
    session_cookie = request.cookies.get(settings.COOKIE_NAME)
    payload = read_session_token(session_cookie)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    user_id = payload.get("sub")
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Only a cookie that resolves to a real user counts as someone using the site. API-key
    # requests never reach this function, and failed lookups raise above before getting here.
    activity.record_cookie_activity()
    return user


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    """Require authenticated user; derive from HTTP-only session cookie."""
    return await _user_from_session_cookie(request, session)


async def get_current_user_id_short_lived(request: Request) -> int:
    """Require an authenticated user, but return only their id, from a session that has
    already committed and closed by the time this returns.

    For long-lived responses (the SSE stream). get_current_user's session comes from get_db, a
    yield dependency whose cleanup FastAPI runs only after the response finishes. For a stream
    that stays open for hours, that left one connection checked out and idle in transaction
    for the stream's whole life, which both exhausted the connection pool and kept the
    database from ever counting as idle. Opening and closing the session here, inside the
    dependency body, makes the lookup independent of when FastAPI runs dependency cleanup."""
    async with AsyncSessionLocal() as session:
        user = await _user_from_session_cookie(request, session)
        user_id = user.id
        await session.commit()
    return user_id
