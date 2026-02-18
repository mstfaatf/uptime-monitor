"""Target endpoints with strict ownership enforcement."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import Check, Target, User

router = APIRouter(prefix="/targets", tags=["targets"])


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


class TargetStatusResponse(BaseModel):
    id: int
    url: str
    name: str | None
    is_up: bool
    checked_at: str | None
    status_code: int | None
    error: str | None

    class Config:
        from_attributes = True


@router.get("/status", response_model=list[TargetStatusResponse])
async def list_targets_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return each target owned by the user with its latest check result."""
    latest = (
        select(Check.target_id, func.max(Check.checked_at).label("max_at"))
        .group_by(Check.target_id)
        .subquery()
    )
    stmt = (
        select(Target, Check)
        .select_from(Target)
        .outerjoin(latest, Target.id == latest.c.target_id)
        .outerjoin(
            Check,
            and_(Check.target_id == Target.id, Check.checked_at == latest.c.max_at),
        )
        .where(Target.user_id == current_user.id)
        .order_by(Target.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    out = []
    for target, check in rows:
        out.append(
            TargetStatusResponse(
                id=target.id,
                url=target.url,
                name=target.name,
                is_up=check.is_up if check else False,
                checked_at=check.checked_at.isoformat() if check and check.checked_at else None,
                status_code=check.status_code if check else None,
                error=check.error if check else None,
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
    """Create a new target owned by the authenticated user."""
    target = Target(
        user_id=current_user.id,
        url=str(body.url),
        name=body.name,
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
    """Delete a target only if it belongs to the authenticated user."""
    result = await db.execute(
        select(Target).where(Target.id == target_id, Target.user_id == current_user.id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    await db.delete(target)
    return None
