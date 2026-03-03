"""Target endpoints with strict ownership enforcement."""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import Check, Target, User

router = APIRouter(prefix="/targets", tags=["targets"])


def normalize_url(url: str) -> str:
    """Trim whitespace, require http/https, normalize trailing slash (remove)."""
    url = url.strip()
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https")
    path = (parsed.path or "/").rstrip("/") or ""
    netloc = parsed.netloc or ""
    if parsed.port and (parsed.scheme == "https" and parsed.port != 443 or parsed.scheme == "http" and parsed.port != 80):
        netloc = f"{parsed.hostname}:{parsed.port}"
    elif parsed.hostname:
        netloc = parsed.hostname
    normalized = f"{parsed.scheme}://{netloc}{path}" if path else f"{parsed.scheme}://{netloc}"
    if parsed.query:
        normalized += "?" + parsed.query
    if parsed.fragment:
        normalized += "#" + parsed.fragment
    return normalized


class TargetCreate(BaseModel):
    url: HttpUrl
    name: str | None = None


class TargetResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str

    class Config:
        from_attributes = True


class LatestCheckResponse(BaseModel):
    checked_at: str | None
    is_up: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None


class TargetStatusResponse(BaseModel):
    id: int
    url: str
    name: str | None
    created_at: str
    latest_check: LatestCheckResponse | None


@router.get("/status", response_model=list[TargetStatusResponse])
async def list_targets_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return each target owned by the user with its latest check (one per target, no duplicates)."""
    latest_check_id = (
        select(Check.id)
        .where(Check.target_id == Target.id)
        .order_by(Check.checked_at.desc())
        .limit(1)
        .correlate(Target)
        .scalar_subquery()
    )
    stmt = (
        select(Target, Check)
        .select_from(Target)
        .outerjoin(Check, Check.id == latest_check_id)
        .where(Target.user_id == current_user.id)
        .order_by(Target.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    out = []
    for target, check in rows:
        latest_check = None
        if check:
            latest_check = LatestCheckResponse(
                checked_at=check.checked_at.isoformat() if check.checked_at else None,
                is_up=check.is_up,
                status_code=check.status_code,
                latency_ms=check.latency_ms,
                error=check.error,
            )
        out.append(
            TargetStatusResponse(
                id=target.id,
                url=target.url,
                name=target.name,
                created_at=target.created_at.isoformat(),
                latest_check=latest_check,
            )
        )
    return out


@router.get("", response_model=list[TargetResponse])
async def list_targets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all targets owned by the authenticated user."""
    result = await db.execute(
        select(Target).where(Target.user_id == current_user.id).order_by(Target.created_at.desc())
    )
    targets = result.scalars().all()
    return [
        TargetResponse(id=t.id, url=t.url, name=t.name, created_at=t.created_at.isoformat())
        for t in targets
    ]


@router.post("", response_model=TargetResponse, status_code=status.HTTP_201_CREATED)
async def create_target(
    body: TargetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new target. URL is normalized; duplicate normalized URL per user returns 409."""
    raw = str(body.url).strip()
    try:
        normalized = normalize_url(raw)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    result = await db.execute(
        select(Target).where(
            Target.user_id == current_user.id,
            Target.normalized_url == normalized,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A target with this URL already exists.",
        )
    target = Target(
        user_id=current_user.id,
        url=raw,
        normalized_url=normalized,
        name=(body.name.strip() or None) if body.name else None,
    )
    db.add(target)
    await db.flush()
    await db.refresh(target)
    return TargetResponse(id=target.id, url=target.url, name=target.name, created_at=target.created_at.isoformat())


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a target only if it belongs to the authenticated user. Checks are removed (CASCADE)."""
    result = await db.execute(
        select(Target).where(Target.id == target_id, Target.user_id == current_user.id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    await db.delete(target)
    return None
