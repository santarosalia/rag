from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.models import Document
from rag.db.models import DocumentStatus as DBDocumentStatus
from rag.db.session import get_db
from rag.generation.service import QueryService
from rag.ingestion.pipeline import create_document_record
from rag.models.schemas import (
    DocumentResponse,
    DocumentStatus,
    DocumentUploadResponse,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from rag.observability.metrics import QUERY_COUNTER
from rag.retrieval.pipeline import RetrievalPipeline
from rag.storage.s3 import ObjectStorage, compute_content_hash


def _enqueue_ingest(doc_id: str, job_id: str):
    from rag.workers.celery_app import ingest_document_task

    return ingest_document_task.delay(doc_id, job_id)


def _enqueue_delete(doc_id: str):
    from rag.workers.celery_app import delete_document_task

    return delete_document_task.delay(doc_id)

router = APIRouter(prefix="/v1")


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str | None = Form(default=None),
    source: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content_hash = compute_content_hash(data)
    storage = ObjectStorage()

    document, job = await create_document_record(
        db,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        content_hash=content_hash,
        s3_key="pending",
        tenant_id=tenant_id,
        source=source,
    )

    stored = storage.upload(data, file.filename, doc_id=document.id)
    document.s3_key = stored.key
    await db.flush()

    task = _enqueue_ingest(str(document.id), str(job.id))
    job.celery_task_id = task.id
    await db.flush()

    return DocumentUploadResponse(
        doc_id=document.id,
        job_id=job.id,
        status=DocumentStatus.PENDING,
    )


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        doc_id=document.id,
        filename=document.filename,
        source=document.source,
        content_type=document.content_type,
        status=DocumentStatus(document.status.value),
        chunk_count=document.chunk_count,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.status == DBDocumentStatus.DELETED:
        return {"doc_id": str(doc_id), "status": "already_deleted"}

    task = _enqueue_delete(str(doc_id))
    return {"doc_id": str(doc_id), "status": "deletion_queued", "task_id": task.id}


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    backend = request.backend.value if request.backend else None
    try:
        pipeline = RetrievalPipeline(backend=backend)
        citations, latency = await pipeline.retrieve(
            query=request.query,
            mode=request.mode,
            tenant_id=request.tenant_id,
            top_k=request.top_k,
            rerank=request.rerank,
        )
        QUERY_COUNTER.labels(endpoint="retrieve", status="success").inc()
        return RetrieveResponse(
            query=request.query,
            mode=request.mode,
            backend=pipeline.backend_name,
            citations=citations,
            latency_ms=latency,
        )
    except Exception:
        QUERY_COUNTER.labels(endpoint="retrieve", status="error").inc()
        raise


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    backend = request.backend.value if request.backend else None
    try:
        service = QueryService(backend=backend)
        response = await service.query(
            query=request.query,
            tenant_id=request.tenant_id,
            top_k=request.top_k,
        )
        QUERY_COUNTER.labels(endpoint="query", status="success").inc()
        return response
    except Exception:
        QUERY_COUNTER.labels(endpoint="query", status="error").inc()
        raise
