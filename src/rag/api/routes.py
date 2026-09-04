from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.api.glossary import router as glossary_router
from rag.api.groups import router as groups_router
from rag.db.models import Document
from rag.db.models import DocumentStatus as DBDocumentStatus
from rag.db.session import get_db
from rag.generation.service import QueryService
from rag.groups.service import require_group, resolve_search_group
from rag.ingestion.parser_client import ParserClient, ParserError
from rag.ingestion.parse_items import load_parse_response
from rag.ingestion.pipeline import create_document_record
from rag.models.parse import ParseResponse
from rag.models.schemas import (
    DocumentResponse,
    DocumentStatus,
    DocumentUploadResponse,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    RetrieveResponse,
    project_citation_bodies,
)
from rag.observability.metrics import QUERY_COUNTER
from rag.retrieval.pipeline import RetrievalPipeline


def _enqueue_ingest(doc_id: str, job_id: str):
    from rag.workers.celery_app import ingest_document_task

    return ingest_document_task.delay(doc_id, job_id)


def _enqueue_delete(doc_id: str):
    from rag.workers.celery_app import delete_document_task

    return delete_document_task.delay(doc_id)


router = APIRouter(prefix="/v1")
router.include_router(groups_router)
router.include_router(glossary_router)


async def _enqueue_parse(
    db: AsyncSession,
    *,
    group_id: str,
    filename: str,
    content_type: str,
    parse: ParseResponse,
) -> DocumentUploadResponse:
    await require_group(db, group_id)
    if parse.status.upper() == "FAIL":
        raise HTTPException(
            status_code=502,
            detail=parse.error or "Parser returned FAIL",
        )
    if not parse.results:
        raise HTTPException(status_code=400, detail="Parse response has no results")

    document, job = await create_document_record(
        db,
        filename=filename,
        content_type=content_type,
        parse=parse,
        group_id=group_id,
    )
    task = _enqueue_ingest(str(document.id), str(job.id))
    job.celery_task_id = task.id
    await db.flush()
    return DocumentUploadResponse(
        doc_id=document.id,
        job_id=job.id,
        status=DocumentStatus.PENDING,
        parse=parse,
    )


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    group_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a source file, parse via Parser Service, then queue ParseResponse ingest."""
    if not group_id or not group_id.strip():
        raise HTTPException(status_code=400, detail="group_id is required")
    citation_name = (file.filename or "").strip()
    if not citation_name:
        raise HTTPException(status_code=400, detail="Filename is required")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        parse = await ParserClient().parse(
            raw,
            filename=citation_name,
            content_type=file.content_type,
        )
    except ParserError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return await _enqueue_parse(
        db,
        group_id=group_id.strip(),
        filename=citation_name,
        content_type=file.content_type or "application/octet-stream",
        parse=parse,
    )


@router.post("/documents/parse/file", response_model=DocumentUploadResponse)
async def upload_parse_file(
    file: UploadFile = File(...),
    group_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload ParseResponse JSON or ResultItem[] and queue ingest (no Parser Service)."""
    if not group_id or not group_id.strip():
        raise HTTPException(status_code=400, detail="group_id is required")
    citation_name = (file.filename or "").strip()
    if not citation_name:
        raise HTTPException(status_code=400, detail="Filename is required")

    raw = await file.read()
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        parse = load_parse_response(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parse JSON: {exc}") from exc

    return await _enqueue_parse(
        db,
        group_id=group_id.strip(),
        filename=citation_name,
        content_type=file.content_type or "application/json",
        parse=parse,
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
        content_type=document.content_type,
        status=DocumentStatus(document.status.value),
        chunk_count=document.chunk_count,
        group_id=document.group_id,
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
async def retrieve(
    request: RetrieveRequest,
    db: AsyncSession = Depends(get_db),
) -> RetrieveResponse:
    try:
        group_id = await resolve_search_group(db, request.group_id)
        pipeline = RetrievalPipeline()
        citations, latency = await pipeline.retrieve(
            query=request.query,
            mode=request.mode,
            group_id=group_id,
            top_k=request.top_k,
            rerank=request.rerank,
        )
        QUERY_COUNTER.labels(endpoint="retrieve", status="success").inc()
        return RetrieveResponse(
            query=request.query,
            mode=request.mode,
            backend=pipeline.backend_name,
            citations=project_citation_bodies(
                citations, snippet=request.snippet, content=request.content
            ),
            latency_ms=latency,
        )
    except HTTPException:
        raise
    except Exception:
        QUERY_COUNTER.labels(endpoint="retrieve", status="error").inc()
        raise


@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    try:
        group_id = await resolve_search_group(db, request.group_id)
        service = QueryService()
        response = await service.query(
            query=request.query,
            group_id=group_id,
            top_k=request.top_k,
        )
        QUERY_COUNTER.labels(endpoint="query", status="success").inc()
        citations = (
            []
            if not request.include_citations
            else project_citation_bodies(
                response.citations,
                snippet=request.snippet,
                content=request.content,
            )
        )
        return response.model_copy(update={"citations": citations})
    except HTTPException:
        raise
    except Exception:
        QUERY_COUNTER.labels(endpoint="query", status="error").inc()
        raise
