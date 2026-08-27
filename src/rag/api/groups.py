from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import DocumentStatus as DBDocumentStatus
from rag.db.session import get_db
from rag.groups.service import (
    create_group,
    delete_group,
    get_group,
    list_group_documents,
    list_groups,
    to_group_response,
    update_group,
)
from rag.models.schemas import (
    DocumentStatus,
    GroupCreate,
    GroupDocumentItem,
    GroupResponse,
    GroupUpdate,
)

router = APIRouter(prefix="/groups")


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group_endpoint(
    body: GroupCreate,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group = await create_group(db, name=body.name, group_id=body.id)
    return to_group_response(group)


@router.get("", response_model=list[GroupResponse])
async def list_groups_endpoint(
    db: AsyncSession = Depends(get_db),
) -> list[GroupResponse]:
    groups = await list_groups(db)
    return [to_group_response(group) for group in groups]


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group_endpoint(
    group_id: str,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return to_group_response(group)


@router.patch("/{group_id}", response_model=GroupResponse)
async def patch_group_endpoint(
    group_id: str,
    body: GroupUpdate,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    updated = await update_group(db, group, name=body.name)
    return to_group_response(updated)


@router.delete("/{group_id}", status_code=204)
async def delete_group_endpoint(
    group_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    await delete_group(db, group)


@router.get("/{group_id}/documents", response_model=list[GroupDocumentItem])
async def list_group_documents_endpoint(
    group_id: str,
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
