import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import get_settings
from rag.db.models import Chunk, Document, DocumentStatus, Group, IngestJob, JobStatus
from rag.indexing.documents import build_index_document
from rag.indexing.factory import get_search_backend
from rag.ingestion.parse_items import load_parse_response, parse_response_to_chunks
from rag.models.parse import ParseResponse
from rag.observability.logging import get_logger
from rag.observability.metrics import INGEST_COUNTER
from rag.retrieval.embeddings import get_embedding_service

logger = get_logger(__name__)


class IngestionPipeline:
    def __init__(self) -> None:
        config = get_settings().yaml_config
        chunk_cfg = config.get("chunking", {})
        ingest_cfg = config.get("ingestion", {})

        self.max_tokens = chunk_cfg.get("max_tokens", 768)
        self.batch_size = ingest_cfg.get("bulk_batch_size", 100)
        self.embedding_service = get_embedding_service()
        self.search_backend = get_search_backend()

    async def ingest_document(
        self,
        session: AsyncSession,
        doc_id: uuid.UUID,
    ) -> int:
        result = await session.execute(
            select(Document).where(Document.id == doc_id)
        )
        document = result.scalar_one_or_none()
        if not document or document.status == DocumentStatus.DELETED:
            raise ValueError(f"Document {doc_id} not found or deleted")

        group_result = await session.execute(select(Group).where(Group.id == document.group_id))
        group = group_result.scalar_one_or_none()
        if group is None:
            raise ValueError(f"Group {document.group_id} not found for document {doc_id}")

        document.status = DocumentStatus.PROCESSING
        await session.flush()

        try:
            parse = load_parse_response(document.parse_json)
            all_text_chunks = parse_response_to_chunks(parse, max_tokens=self.max_tokens)

            await session.execute(delete(Chunk).where(Chunk.doc_id == document.id))
            await session.flush()

            if not all_text_chunks:
                raise ValueError("No content extracted from document")

            searchable_chunks = [c for c in all_text_chunks if c.searchable]
            texts = [c.content for c in searchable_chunks]
            embeddings = (
                self.embedding_service.embed_texts(texts) if texts else []
            )
            embed_by_index = {
                c.chunk_index: emb
                for c, emb in zip(searchable_chunks, embeddings, strict=True)
            }

            db_chunks: list[Chunk] = []
            index_docs = []
            id_by_index: dict[int, uuid.UUID] = {}

            for text_chunk in all_text_chunks:
                chunk_id = uuid.uuid4()
                id_by_index[text_chunk.chunk_index] = chunk_id
                parent_chunk_id = None
                if text_chunk.parent_chunk_index is not None:
                    parent_chunk_id = id_by_index.get(text_chunk.parent_chunk_index)

                db_chunk = Chunk(
                    id=chunk_id,
                    doc_id=document.id,
                    group_id=document.group_id,
                    chunk_index=text_chunk.chunk_index,
                    content=text_chunk.content,
                    token_count=text_chunk.token_count,
                    page=text_chunk.page,
                    type=text_chunk.type,
                    bbox=text_chunk.bbox,
                    parent_chunk_id=parent_chunk_id,
                )
                db_chunks.append(db_chunk)

                embedding = embed_by_index.get(text_chunk.chunk_index)
                if embedding is None:
                    continue

                index_docs.append(
                    build_index_document(
                        chunk_id=str(chunk_id),
                        doc_id=str(document.id),
                        content=text_chunk.content,
                        embedding=embedding,
                        group_id=str(document.group_id),
                        filename=document.filename,
                        page=text_chunk.page,
                        chunk_index=text_chunk.chunk_index,
                        token_count=text_chunk.token_count,
                    )
                )

            session.add_all(db_chunks)
            await session.flush()
            # Rows must be committed before UPDATE so the same worker session
            # (or a later statement) can see them after DDL / a prior commit.
            await session.commit()
            await self.search_backend.ensure_index(session)

            for i in range(0, len(index_docs), self.batch_size):
                batch = index_docs[i : i + self.batch_size]
                success, errors = await self.search_backend.bulk_index(batch, session)
                if errors:
                    raise RuntimeError(f"Failed to index {errors} chunks")

            document.status = DocumentStatus.COMPLETED
            document.chunk_count = len(db_chunks)
            document.error_message = None
            document.updated_at = datetime.now(UTC)

            INGEST_COUNTER.labels(status="success").inc()
            logger.info(
                "document_ingested",
                doc_id=str(doc_id),
                chunk_count=len(db_chunks),
                backend=self.search_backend.name,
            )
            return len(db_chunks)

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            INGEST_COUNTER.labels(status="failed").inc()
            logger.error("document_ingest_failed", doc_id=str(doc_id), error=str(e))
            raise


async def create_document_record(
    session: AsyncSession,
    *,
    filename: str,
    content_type: str,
    parse: ParseResponse | dict[str, Any],
    group_id: str,
) -> tuple[Document, IngestJob]:
    if isinstance(parse, ParseResponse):
        parse_json = parse.model_dump(mode="json")
    else:
        parse_json = parse

    document = Document(
        filename=filename,
        content_type=content_type,
        parse_json=parse_json,
        group_id=group_id,
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    await session.flush()

    job = IngestJob(
        doc_id=document.id,
        idempotency_key=str(document.id),
        status=JobStatus.PENDING,
    )
    session.add(job)
    await session.flush()

    return document, job
