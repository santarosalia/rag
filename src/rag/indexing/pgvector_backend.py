from typing import Any

from sqlalchemy import text

from rag.db.session import AsyncSessionLocal
from rag.indexing.morphology import get_morph_analyzer
from rag.observability.logging import get_logger

logger = get_logger(__name__)


class PgVectorBackend:
    """PostgreSQL pgvector (dense) + tsvector FTS with Kiwi morphology (sparse)."""

    @property
    def name(self) -> str:
        return "pgvector"

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
                result = await session.execute(
                    text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
                return bool(result.scalar())
        except Exception as e:
            logger.warning("pgvector_ping_failed", error=str(e))
            return False

    async def ensure_index(self) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
                    ON chunks USING hnsw (embedding vector_cosine_ops)
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chunks_tsv_gin
                    ON chunks USING GIN (tsv)
                    """
                )
            )
            await session.commit()
            logger.info("pgvector_indexes_ensured")

    async def bulk_index(self, documents: list[dict[str, Any]]) -> tuple[int, int]:
        if not documents:
            return 0, 0

        morph = get_morph_analyzer()
        success = 0
        errors = 0

        async with AsyncSessionLocal() as session:
            for doc in documents:
                try:
                    chunk_id = doc["chunk_id"]
                    content = doc.get("content", "")
                    content_morph = morph.analyze(content)
                    embedding = doc["embedding"]
                    embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"

                    result = await session.execute(
                        text(
                            """
                            UPDATE chunks
                            SET content_morph = :content_morph,
                                embedding = CAST(:embedding AS vector),
                                tsv = to_tsvector('simple', :content_morph)
                            WHERE id = CAST(:chunk_id AS uuid)
                            """
                        ),
                        {
                            "chunk_id": chunk_id,
                            "content_morph": content_morph,
                            "embedding": embedding_literal,
                        },
                    )
                    if result.rowcount == 0:
                        raise RuntimeError(f"chunk {chunk_id} not found for embedding update")
                    success += 1
                except Exception as e:
                    errors += 1
                    logger.warning(
                        "pgvector_bulk_index_chunk_failed",
                        chunk_id=doc.get("chunk_id"),
                        error=str(e),
                    )
            await session.commit()

        return success, errors

    async def delete_by_doc_id(self, doc_id: str) -> int:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE chunks
                    SET embedding = NULL, content_morph = NULL, tsv = NULL
                    WHERE doc_id = CAST(:doc_id AS uuid)
                    """
                ),
                {"doc_id": doc_id},
            )
            await session.commit()
            return result.rowcount or 0

    async def knn_search(
        self,
        embedding: list[float],
        k: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        tenant_clause = "AND c.tenant_id = :tenant_id" if tenant_id else ""

        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.doc_id::text AS doc_id,
                c.content,
                d.source,
                d.filename,
                c.page,
                1 - (c.embedding <=> CAST(:embedding AS vector)) AS score
            FROM chunks c
            JOIN documents d ON c.doc_id = d.id
            WHERE c.embedding IS NOT NULL
              AND d.status = 'completed'
              {tenant_clause}
            ORDER BY c.embedding <=> CAST(:embedding AS vector)
            LIMIT :k
        """

        async with AsyncSessionLocal() as session:
            params: dict[str, Any] = {"embedding": embedding_literal, "k": k}
            if tenant_id:
                params["tenant_id"] = tenant_id
            result = await session.execute(text(sql), params)
            return self._rows_to_hits(result.mappings().all())

    async def bm25_search(
        self,
        query_text: str,
        k: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        morph = get_morph_analyzer()
        morph_query = morph.analyze(query_text)
        if not morph_query.strip():
            morph_query = query_text

        tenant_clause = "AND c.tenant_id = :tenant_id" if tenant_id else ""

        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.doc_id::text AS doc_id,
                c.content,
                d.source,
                d.filename,
                c.page,
                ts_rank(c.tsv, plainto_tsquery('simple', :morph_query)) AS score
            FROM chunks c
            JOIN documents d ON c.doc_id = d.id
            WHERE c.tsv IS NOT NULL
              AND c.tsv @@ plainto_tsquery('simple', :morph_query)
              AND d.status = 'completed'
              {tenant_clause}
            ORDER BY score DESC
            LIMIT :k
        """

        async with AsyncSessionLocal() as session:
            params: dict[str, Any] = {"morph_query": morph_query, "k": k}
            if tenant_id:
                params["tenant_id"] = tenant_id
            result = await session.execute(text(sql), params)
            return self._rows_to_hits(result.mappings().all())

    @staticmethod
    def _rows_to_hits(rows: list[Any]) -> list[dict[str, Any]]:
        hits = []
        for rank, row in enumerate(rows, start=1):
            hits.append(
                {
                    "chunk_id": row["chunk_id"],
                    "doc_id": row["doc_id"],
                    "content": row["content"] or "",
                    "source": row["source"] or "",
                    "filename": row["filename"] or "",
                    "page": row["page"],
                    "score": float(row["score"] or 0.0),
                    "rank": rank,
                }
            )
        return hits
