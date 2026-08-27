from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import get_settings
from rag.db.models import Chunk, Document, Group
from rag.groups.policy import can_delete_group, exceeds_after_move, new_child_depth
from rag.groups.tree import (
    child_path,
    exceeds_max_depth,
    rewrite_subtree_path,
    root_path,
    would_create_cycle,
)
from rag.models.schemas import GroupResponse


def get_max_depth() -> int:
    return int(get_settings().yaml_config.get("groups", {}).get("max_depth", 8))


def to_group_response(group: Group) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        parent_id=group.parent_id,
        name=group.name,
        slug=group.slug,
        path=group.path,
        depth=group.depth,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


async def get_group(session: AsyncSession, group_id: UUID) -> Group | None:
    result = await session.execute(select(Group).where(Group.id == group_id))
    return result.scalar_one_or_none()


async def require_group(session: AsyncSession, group_id: UUID) -> Group:
    group = await get_group(session, group_id)
    if group is None:
        raise HTTPException(status_code=400, detail="Group not found")
    return group


async def resolve_search_group(
    session: AsyncSession,
    group_id: UUID | None,
    include_descendants: bool,
) -> tuple[UUID | None, bool, str | None]:
    if group_id is None:
        return None, False, None
    group = await require_group(session, group_id)
    path = group.path if include_descendants else None
    return group.id, include_descendants, path


async def _ensure_unique_name(
    session: AsyncSession,
    parent_id: UUID | None,
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(Group).where(Group.name == name)
    if parent_id is None:
        stmt = stmt.where(Group.parent_id.is_(None))
    else:
        stmt = stmt.where(Group.parent_id == parent_id)
    if exclude_id is not None:
        stmt = stmt.where(Group.id != exclude_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A group with this name already exists under the same parent",
        )


async def create_group(session: AsyncSession, name: str, parent_id: UUID | None) -> Group:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    parent = None
    if parent_id is not None:
        parent = await require_group(session, parent_id)
    depth = new_child_depth(parent.depth if parent else None)
    max_depth = get_max_depth()
    if exceeds_max_depth(depth, max_depth):
        raise HTTPException(
            status_code=400,
            detail=f"Group depth must be less than {max_depth}",
        )
    await _ensure_unique_name(session, parent_id, name)

    group = Group(name=name, parent_id=parent_id, path="", depth=depth)
    session.add(group)
    await session.flush()
    group.path = child_path(parent.path, group.id) if parent else root_path(group.id)
    await session.flush()
    # onupdate=func.now() expires updated_at after the path UPDATE; accessing it
    # without an explicit refresh triggers a sync lazy load (MissingGreenlet).
    await session.refresh(group)
    return group


async def list_groups(session: AsyncSession, parent_id: UUID | None = None) -> list[Group]:
    stmt = select(Group).where(Group.parent_id == parent_id).order_by(Group.name)
    if parent_id is None:
        stmt = select(Group).where(Group.parent_id.is_(None)).order_by(Group.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_all_groups(session: AsyncSession) -> list[Group]:
    result = await session.execute(select(Group).order_by(Group.depth, Group.name))
    return list(result.scalars().all())


async def list_children(session: AsyncSession, parent_id: UUID) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.parent_id == parent_id).order_by(Group.name)
    )
    return list(result.scalars().all())


async def list_group_documents(session: AsyncSession, group_id: UUID) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.group_id == group_id).order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def update_group(
    session: AsyncSession,
    group: Group,
    *,
    name: str | None,
    parent_id: UUID | None,
    parent_id_set: bool,
) -> Group:
    locked = await session.execute(select(Group).where(Group.id == group.id).with_for_update())
    group = locked.scalar_one()

    next_parent_id = parent_id if parent_id_set else group.parent_id
    next_name = name.strip() if name is not None else group.name
    if next_name != group.name or next_parent_id != group.parent_id:
        await _ensure_unique_name(session, next_parent_id, next_name, exclude_id=group.id)

    if name is not None:
        group.name = next_name

    if parent_id_set and parent_id != group.parent_id:
        await _move_group(session, group, parent_id)

    await session.flush()
    await session.refresh(group)
    return group


async def _move_group(session: AsyncSession, group: Group, new_parent_id: UUID | None) -> None:
    new_parent = None
    if new_parent_id is not None:
        new_parent = await require_group(session, new_parent_id)
        await session.execute(select(Group).where(Group.id == new_parent.id).with_for_update())

    if would_create_cycle(
        group.id,
        group.path,
        new_parent.id if new_parent else None,
        new_parent.path if new_parent else None,
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot move a group under itself or a descendant",
        )

    subtree_max = (
        await session.execute(
            select(func.max(Group.depth)).where(
                (Group.path == group.path) | Group.path.startswith(group.path + "/")
            )
        )
    ).scalar() or group.depth
    if exceeds_after_move(
        moving_depth=group.depth,
        subtree_max_depth=subtree_max,
        new_parent_depth=new_parent.depth if new_parent else None,
        max_depth=get_max_depth(),
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Move would exceed max group depth of {get_max_depth()}",
        )

    old_path = group.path
    new_path = child_path(new_parent.path, group.id) if new_parent else root_path(group.id)
    new_depth = new_child_depth(new_parent.depth if new_parent else None)
    delta = new_depth - group.depth

    subtree = (
        (
            await session.execute(
                select(Group)
                .where((Group.path == old_path) | Group.path.startswith(old_path + "/"))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for node in subtree:
        node.path = rewrite_subtree_path(old_path, new_path, node.path)
        node.depth = node.depth + delta
        if node.id == group.id:
            node.parent_id = new_parent_id

    chunks = (
        (
            await session.execute(
                select(Chunk).where(
                    (Chunk.group_path == old_path) | Chunk.group_path.startswith(old_path + "/")
                )
            )
        )
        .scalars()
        .all()
    )
    for chunk in chunks:
        chunk.group_path = rewrite_subtree_path(old_path, new_path, chunk.group_path)


async def delete_group(session: AsyncSession, group: Group) -> None:
    child_count = (
        await session.execute(
            select(func.count()).select_from(Group).where(Group.parent_id == group.id)
        )
    ).scalar_one()
    doc_count = (
        await session.execute(
            select(func.count()).select_from(Document).where(Document.group_id == group.id)
        )
    ).scalar_one()
    if not can_delete_group(has_children=child_count > 0, has_documents=doc_count > 0):
        raise HTTPException(
            status_code=409,
            detail="Group still has child groups or documents",
        )
    await session.delete(group)
    await session.flush()
