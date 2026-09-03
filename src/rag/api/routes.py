from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.api.groups import router as groups_router
from rag.db.models import Document
from rag.db.models import DocumentStatus as DBDocumentStatus
from rag.db.session import get_db
from rag.generation.service import QueryService
from rag.groups.service import require_group, resolve_search_group
from rag.ingestion.parser_client import ParserClient, ParserError
from rag.ingestion.pipeline import create_document_record
from rag.models.parse import ParseResponse
from rag.models.schemas import (
    DocumentResponse,
    DocumentStatus,
    DocumentUploadResponse,
    ParsedDocumentRequest,
    QueryRequest,
    QueryResponse,
    RetrieveRequest,
    RetrieveResponse,
    project_citation_bodies,
)
from rag.observability.metrics import QUERY_COUNTER
from rag.retrieval.pipeline import RetrievalPipeline
from rag.storage.s3 import ObjectStorage


def _enqueue_ingest(doc_id: str, job_id: str):
    from rag.workers.celery_app import ingest_document_task

    return ingest_document_task.delay(doc_id, job_id)


def _enqueue_delete(doc_id: str):
    from rag.workers.celery_app import delete_document_task

    return delete_document_task.delay(doc_id)


router = APIRouter(prefix="/v1")
router.include_router(groups_router)


async def _enqueue_markdown(
    db: AsyncSession,
    *,
    group_id: str,
    filename: str,
    content_type: str,
    data: bytes,
    parse: ParseResponse | None = None,
) -> DocumentUploadResponse:
    await require_group(db, group_id)
    storage = ObjectStorage()
    document, job = await create_document_record(
        db,
        filename=filename,
        content_type=content_type,
        s3_key="pending",
        group_id=group_id,
    )
    stored = storage.upload(data, "content.md", doc_id=document.id)
    document.s3_key = stored.key
    await db.flush()
    task = _enqueue_ingest(str(document.id), str(job.id))
    job.celery_task_id = task.id
    await db.flush()
    return DocumentUploadResponse(
        doc_id=document.id,
        job_id=job.id,
        status=DocumentStatus.PENDING,
        parse=parse,
    )


def _utf8_markdown(data: bytes) -> bytes:
    text = data.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise HTTPException(status_code=400, detail="markdown is required")
    return text.encode("utf-8")


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    group_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a source file, parse via Parser Service, then queue Markdown ingest."""
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
            output_format="markdown",
        )
        markdown = parse.markdown_text()
    except ParserError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return await _enqueue_markdown(
        db,
        group_id=group_id.strip(),
        filename=citation_name,
        content_type=file.content_type or "application/octet-stream",
        data=markdown.encode("utf-8"),
        parse=parse,
    )


@router.post("/documents/parsed", response_model=DocumentUploadResponse)
async def upload_parsed_document(
    body: ParsedDocumentRequest,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    markdown = body.markdown.strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="markdown is required")
    filename = body.filename.strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")

    return await _enqueue_markdown(
        db,
        group_id=body.group_id,
        filename=filename,
        content_type=body.content_type or "text/markdown",
        data=markdown.encode("utf-8"),
    )


@router.post("/documents/parsed/file", response_model=DocumentUploadResponse)
async def upload_parsed_markdown_file(
    file: UploadFile = File(...),
    group_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    if not group_id or not group_id.strip():
        raise HTTPException(status_code=400, detail="group_id is required")
    citation_name = (file.filename or "").strip()
    if not citation_name:
        raise HTTPException(status_code=400, detail="Filename is required")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    data = _utf8_markdown(raw)
    return await _enqueue_markdown(
        db,
        group_id=group_id.strip(),
        filename=citation_name,
        content_type=file.content_type or "text/markdown",
        data=data,
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
