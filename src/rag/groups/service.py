from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import Document, Group
from rag.groups.ids import InvalidGroupId, parse_group_id, resolve_create_id
from rag.models.schemas import GroupResponse


def to_group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        slug=group.slug,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _http_group_id(value: str | None, *, required: bool = True) -> str | None:
    try:
        return parse_group_id(value, required=required)
    except InvalidGroupId as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def get_group(session: AsyncSession, group_id: str) -> Group | None:
    gid = _http_group_id(group_id, required=True)
    result = await session.execute(select(Group).where(Group.id == gid))
    return result.scalar_one_or_none()


async def require_group(session: AsyncSession, group_id: str) -> Group:
    group = await get_group(session, group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Group not found")
    return group


async def resolve_search_group(session: AsyncSession, group_id: str | None) -> str | None:
    if group_id is None or not str(group_id).strip():
        return None
    group = await require_group(session, group_id)
    return group.id


async def _ensure_unique_name(
    session: AsyncSession,
    name: str,
    *,
    exclude_id: str | None = None,
) -> None:
    stmt = select(Group).where(Group.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Group.id != exclude_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A group with this name already exists",
        )


async def create_group(session: AsyncSession, name: str, group_id: str | None = None) -> Group:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    try:
        gid = resolve_create_id(group_id)
    except InvalidGroupId as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if await get_group(session, gid) is not None:
        raise HTTPException(status_code=409, detail="A group with this id already exists")
    await _ensure_unique_name(session, name)

    group = Group(id=gid, name=name)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    result = await session.execute(select(Group).order_by(Group.name))
    return list(result.scalars().all())


async def list_group_documents(session: AsyncSession, group_id: str) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.group_id == group_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def update_group(session: AsyncSession, group: Group, *, name: str | None) -> Group:
    locked = await session.execute(select(Group).where(Group.id == group.id).with_for_update())
    group = locked.scalar_one()

    if name is not None:
        next_name = name.strip()
        if not next_name:
            raise HTTPException(status_code=400, detail="Group name is required")
        if next_name != group.name:
            await _ensure_unique_name(session, next_name, exclude_id=group.id)
        group.name = next_name

    await session.flush()
    await session.refresh(group)
    return group


async def delete_group(session: AsyncSession, group: Group) -> None:
    doc_count = (
        await session.execute(
            select(func.count()).select_from(Document).where(Document.group_id == group.id)
        )
    ).scalar_one()
    if doc_count > 0:
        raise HTTPException(status_code=409, detail="Group still has documents")
    await session.delete(group)
    await session.flush()
