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
from rag.indexing.factory import get_search_backend
from rag.ingestion.parse_items import load_parse_response
from rag.ingestion.parser_client import ParserClient, ParserError
from rag.ingestion.pipeline import IngestionPipeline, create_document_record
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

router = APIRouter(prefix="/v1")
router.include_router(groups_router)
router.include_router(glossary_router)


def _validate_parse(parse: ParseResponse) -> None:
    if parse.status.upper() == "FAIL":
        raise HTTPException(
            status_code=502,
            detail=parse.error or "Parser returned FAIL",
        )
    if not parse.results:
        raise HTTPException(status_code=400, detail="Parse response has no results")


def _parse_metadata_form(raw: str | None) -> dict | None:
    if raw is None or not str(raw).strip():
        return None
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid metadata JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="metadata must be a JSON object")
    return value


def _parse_tag_form(raw: str | None) -> list[str] | None:
    """Accept JSON array string (``["a","b"]``) or a single tag string."""
    if raw is None or not str(raw).strip():
        return None
    import json

    text = str(raw).strip()
    if text.startswith("["):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid tag JSON: {exc}") from exc
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(status_code=400, detail="tag must be a JSON array of strings")
        return value
    return [text]


async def _run_index(db: AsyncSession, document: Document) -> DocumentUploadResponse:
    try:
        parse = load_parse_response(document.parse_json)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parse_json: {exc}") from exc
    _validate_parse(parse)

    pipeline = IngestionPipeline()
    try:
        await pipeline.ingest_document(db, document.id)
    finally:
        await pipeline.search_backend.close()

    await db.refresh(document)
    return DocumentUploadResponse(
        doc_id=document.id,
        status=DocumentStatus(document.status.value),
        chunk_count=document.chunk_count,
        message="Document indexed",
        parse=parse,
    )


@router.post("/documents/files", response_model=DocumentUploadResponse)
async def upload_document_file(
    file: UploadFile = File(...),
    group_id: str | None = Form(default=None),
    tag: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a source file, parse via Parser Service, then index synchronously."""
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

    _validate_parse(parse)
    await require_group(db, group_id.strip())
    document = await create_document_record(
        db,
        filename=citation_name,
        content_type=file.content_type or "application/octet-stream",
        parse=parse,
        group_id=group_id.strip(),
        tag=_parse_tag_form(tag),
        document_metadata=_parse_metadata_form(metadata),
    )
    return await _run_index(db, document)


@router.post("/documents/{doc_id}/index", response_model=DocumentUploadResponse)
async def index_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Build chunks/embeddings from ``documents.parse_json`` for an existing document."""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status == DBDocumentStatus.DELETED:
        raise HTTPException(status_code=409, detail="Document is deleted")

    return await _run_index(db, document)


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
        tag=document.tag,
        metadata=document.document_metadata,
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

    from datetime import UTC, datetime

    backend = get_search_backend()
    try:
        await backend.delete_by_doc_id(str(doc_id), db)
    finally:
        await backend.close()

    document.status = DBDocumentStatus.DELETED
    document.deleted_at = datetime.now(UTC)
    await db.flush()
    return {"doc_id": str(doc_id), "status": "deleted"}


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
            tag=request.tag,
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
            tag=request.tag,
            top_k=request.top_k,
            include_glossary_definitions=request.include_glossary_definitions,
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
