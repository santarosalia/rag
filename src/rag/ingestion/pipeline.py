import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.config import get_settings
from rag.db.models import Chunk, Document, DocumentStatus, Group, IngestJob, JobStatus
from rag.indexing.documents import build_index_document
from rag.indexing.factory import get_search_backend
from rag.ingestion.chunker import MarkdownChunker, TextChunk
from rag.ingestion.markdown import to_markdown
from rag.observability.logging import get_logger
from rag.observability.metrics import INGEST_COUNTER
from rag.retrieval.embeddings import get_embedding_service
from rag.storage.s3 import ObjectStorage

logger = get_logger(__name__)


class IngestionPipeline:
    def __init__(self) -> None:
        config = get_settings().yaml_config
        chunk_cfg = config.get("chunking", {})
        ingest_cfg = config.get("ingestion", {})

        self.chunker = MarkdownChunker(
            max_tokens=chunk_cfg.get("max_tokens", 768),
            parent_max_tokens=chunk_cfg.get("parent_max_tokens", 2048),
            overlap_tokens=chunk_cfg.get("overlap_tokens", 128),
        )
        self.batch_size = ingest_cfg.get("bulk_batch_size", 100)
        self.storage = ObjectStorage()
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
            data = self.storage.download(document.s3_key)
            markdown = to_markdown(
                data,
                filename=document.filename,
                already_markdown=document.parse_kind == "markdown",
            )

            await session.execute(delete(Chunk).where(Chunk.doc_id == document.id))
            await session.flush()

            all_text_chunks = self.chunker.chunk(markdown)

            if not all_text_chunks:
                raise ValueError("No content extracted from document")

            parents = [c for c in all_text_chunks if c.role == "parent"]
            children = [c for c in all_text_chunks if c.role == "child"]
            if not children:
                raise ValueError("No searchable child chunks extracted from document")

            parent_id_by_key = self._insert_parents(session, document, parents)
            await session.flush()
            child_rows, index_docs = self._prepare_children(
                document,
                children,
                parent_id_by_key,
            )

            session.add_all(child_rows)
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
            document.chunk_count = len(children)
            document.error_message = None
            document.updated_at = datetime.now(UTC)

            INGEST_COUNTER.labels(status="success").inc()
            logger.info(
                "document_ingested",
                doc_id=str(doc_id),
                chunk_count=len(children),
                parent_count=len(parents),
                backend=self.search_backend.name,
            )
            return len(children)

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            INGEST_COUNTER.labels(status="failed").inc()
            logger.error("document_ingest_failed", doc_id=str(doc_id), error=str(e))
            raise

    def _insert_parents(
        self,
        session: AsyncSession,
        document: Document,
        parents: list[TextChunk],
    ) -> dict[str, uuid.UUID]:
        parent_id_by_key: dict[str, uuid.UUID] = {}
        db_parents: list[Chunk] = []
        for parent in parents:
            if parent.parent_key is None:
                continue
            chunk_id = uuid.uuid4()
            parent_id_by_key[parent.parent_key] = chunk_id
            db_parents.append(
                Chunk(
                    id=chunk_id,
                    doc_id=document.id,
                    group_id=document.group_id,
                    chunk_index=parent.chunk_index,
                    content=parent.content,
                    token_count=parent.token_count,
                    page=parent.page,
                    role="parent",
                    kind=parent.kind,
                    parent_chunk_id=None,
                )
            )
        if db_parents:
            session.add_all(db_parents)
        return parent_id_by_key

    def _prepare_children(
        self,
        document: Document,
        children: list[TextChunk],
        parent_id_by_key: dict[str, uuid.UUID],
    ) -> tuple[list[Chunk], list[dict]]:
        texts = [c.content for c in children]
        embeddings = self.embedding_service.embed_texts(texts)

        db_chunks: list[Chunk] = []
        index_docs: list[dict] = []
        for text_chunk, embedding in zip(children, embeddings, strict=True):
            chunk_id = uuid.uuid4()
            parent_chunk_id = (
                parent_id_by_key.get(text_chunk.parent_key)
                if text_chunk.parent_key
                else None
            )
            db_chunks.append(
                Chunk(
                    id=chunk_id,
                    doc_id=document.id,
                    group_id=document.group_id,
                    chunk_index=text_chunk.chunk_index,
                    content=text_chunk.content,
                    token_count=text_chunk.token_count,
                    page=text_chunk.page,
                    role="child",
                    kind=text_chunk.kind,
                    parent_chunk_id=parent_chunk_id,
                )
            )
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
        return db_chunks, index_docs


async def create_document_record(
    session: AsyncSession,
    *,
    filename: str,
    content_type: str,
    s3_key: str,
    group_id: str,
    parse_kind: str = "original",
) -> tuple[Document, IngestJob]:
    document = Document(
        filename=filename,
        content_type=content_type,
        s3_key=s3_key,
        group_id=group_id,
        parse_kind=parse_kind,
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
