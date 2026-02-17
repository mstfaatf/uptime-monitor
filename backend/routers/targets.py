"""Target endpoints with strict ownership enforcement."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import Target, User

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
