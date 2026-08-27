from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import Document, Group
from rag.groups.ids import InvalidGroupId, parse_group_id, resolve_create_id
from rag.models.schemas import GroupResponse


def to_group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        id=group.id,
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


async def create_group(session: AsyncSession, group_id: str | None = None) -> Group:
    try:
        gid = resolve_create_id(group_id)
    except InvalidGroupId as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if await get_group(session, gid) is not None:
        raise HTTPException(status_code=409, detail="A group with this id already exists")

    group = Group(id=gid)
    session.add(group)
    await session.flush()
    await session.refresh(group)
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    result = await session.execute(select(Group).order_by(Group.id))
    return list(result.scalars().all())


async def list_group_documents(session: AsyncSession, group_id: str) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.group_id == group_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


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
