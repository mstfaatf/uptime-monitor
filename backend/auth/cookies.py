"""HTTP-only cookie-based session (JWT in cookie)."""

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import Response
from jose import JWTError, jwt

from config import settings


def _create_token(payload: dict[str, Any]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {**payload, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def create_session_cookie(response: Response, user_id: int, email: str) -> None:
    token = _create_token({"sub": str(user_id), "email": email})
    response.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=settings.COOKIE_MAX_AGE,
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )


def read_session_token(cookie_value: str | None) -> dict[str, Any] | None:
    if not cookie_value:
        return None
    return _decode_token(cookie_value)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.COOKIE_NAME,
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
