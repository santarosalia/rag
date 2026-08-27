from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import DocumentStatus as DBDocumentStatus
from rag.db.session import get_db
from rag.groups.service import (
    create_group,
    delete_group,
    get_group,
    list_all_groups,
    list_children,
    list_group_documents,
    list_groups,
    to_group_response,
    update_group,
)
from rag.groups.tree import assemble_tree
from rag.models.schemas import (
    DocumentStatus,
    GroupCreate,
    GroupDetailResponse,
    GroupDocumentItem,
    GroupResponse,
    GroupTreeNode,
    GroupUpdate,
)

router = APIRouter(prefix="/groups")


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group_endpoint(
    body: GroupCreate,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group = await create_group(db, name=body.name, parent_id=body.parent_id)
    return to_group_response(group)


@router.get("", response_model=list[GroupResponse])
async def list_groups_endpoint(
    parent_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[GroupResponse]:
    groups = await list_groups(db, parent_id=parent_id)
    return [to_group_response(group) for group in groups]


@router.get("/tree", response_model=list[GroupTreeNode])
async def get_group_tree(db: AsyncSession = Depends(get_db)) -> list[GroupTreeNode]:
    groups = await list_all_groups(db)
    return assemble_tree(groups)


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group_endpoint(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> GroupDetailResponse:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    children = await list_children(db, group.id)
    payload = to_group_response(group)
    return GroupDetailResponse(
        **payload.model_dump(),
        children=[to_group_response(child) for child in children],
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def patch_group_endpoint(
    group_id: UUID,
    body: GroupUpdate,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    updated = await update_group(
        db,
        group,
        name=body.name,
        parent_id=body.parent_id,
        parent_id_set="parent_id" in body.model_fields_set,
    )
    return to_group_response(updated)


@router.delete("/{group_id}", status_code=204)
async def delete_group_endpoint(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    await delete_group(db, group)


@router.get("/{group_id}/documents", response_model=list[GroupDocumentItem])
async def list_group_documents_endpoint(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[GroupDocumentItem]:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    documents = await list_group_documents(db, group.id)
    return [
        GroupDocumentItem(
            doc_id=document.id,
            filename=document.filename,
            status=DocumentStatus(document.status.value),
            chunk_count=document.chunk_count,
            created_at=document.created_at,
        )
        for document in documents
        if document.status != DBDocumentStatus.DELETED
    ]
