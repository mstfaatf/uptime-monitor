"""Tag CRUD endpoints (Phase 6, prompt 6.4). Ownership enforced identically to every other
user-owned resource in this app (CLAUDE.md rule 1) — every query here filters by
Tag.user_id == current_user.id. Attaching/detaching a tag to/from a target lives in
routers/targets.py instead (POST /targets/{id}/tags, DELETE /targets/{id}/tags/{tag_id}) since
those endpoints are ownership-scoped on the target first.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import Tag, User

router = APIRouter(prefix="/tags", tags=["tags"])

MAX_TAG_NAME_LENGTH = 100


class TagCreate(BaseModel):
    name: str


class TagResponse(BaseModel):
    id: int
    name: str
    created_at: str

    class Config:
        from_attributes = True


def _tag_to_response(tag: Tag) -> TagResponse:
    return TagResponse(id=tag.id, name=tag.name, created_at=tag.created_at.isoformat())


@router.get("", response_model=list[TagResponse])
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all tags owned by the authenticated user, alphabetically."""
    result = await db.execute(select(Tag).where(Tag.user_id == current_user.id).order_by(Tag.name))
    return [_tag_to_response(t) for t in result.scalars().all()]


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tag. Duplicate name for the same user returns 409 — same convention as
    duplicate-target-URL handling in routers/targets.py. A tag name is only unique per user,
    not globally: two different users can each have their own tag named "production"."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tag name cannot be empty")
    if len(name) > MAX_TAG_NAME_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tag name must be at most {MAX_TAG_NAME_LENGTH} characters",
        )

    result = await db.execute(select(Tag).where(Tag.user_id == current_user.id, Tag.name == name))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A tag with this name already exists.")

    tag = Tag(user_id=current_user.id, name=name)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return _tag_to_response(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tag only if it belongs to the authenticated user. Every target_tags row
    referencing it is removed via ON DELETE CASCADE at the database level — no explicit
    detach-from-every-target step needed here. 404 (not 403) if it doesn't exist or isn't
    owned by the caller, same pattern as every other ownership-scoped endpoint."""
    result = await db.execute(select(Tag).where(Tag.id == tag_id, Tag.user_id == current_user.id))
    tag = result.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    await db.delete(tag)
    return None
