import time
from typing import Any

from rag.config import get_settings
from rag.indexing.factory import get_search_backend
from rag.models.schemas import Citation, SearchMode
from rag.observability.logging import get_logger
from rag.observability.metrics import RETRIEVAL_LATENCY
from rag.retrieval.embeddings import (
    QueryEmbeddingCache,
    get_embedding_cache,
    get_embedding_service,
    get_reranker_service,
)
from rag.retrieval.fusion import rrf_fuse

logger = get_logger(__name__)


class RetrievalPipeline:
    def __init__(
        self,
        embedding_cache: QueryEmbeddingCache | None = None,
    ) -> None:
        self.search_backend = get_search_backend()
        self.embedding_service = get_embedding_service()
        self.reranker_service = get_reranker_service()
        self.embedding_cache = embedding_cache or get_embedding_cache()
        self.config = get_settings().yaml_config.get("retrieval", {})

    @property
    def backend_name(self) -> str:
        return self.search_backend.name

    async def retrieve(
        self,
        query: str,
        mode: SearchMode = SearchMode.HYBRID,
        group_id: str | None = None,
        top_k: int | None = None,
        rerank: bool = True,
    ) -> tuple[list[Citation], dict[str, float]]:
        latency: dict[str, float] = {}
        dense_k = self.config.get("dense_k", 50)
        sparse_k = self.config.get("sparse_k", 50)
        rerank_top_n = top_k or self.config.get("rerank_top_n", 5)
        rerank_input_k = self.config.get("rerank_input_k", 50)
        expand_to_parent = bool(self.config.get("expand_to_parent", True))

        t0 = time.perf_counter()
        embedding = await self._get_query_embedding(query)
        latency["embedding_ms"] = (time.perf_counter() - t0) * 1000

        hits: list[dict[str, Any]] = []
        dense_hits: list[dict[str, Any]] = []
        sparse_hits: list[dict[str, Any]] = []

        if mode in (SearchMode.DENSE, SearchMode.HYBRID):
            t0 = time.perf_counter()
            dense_hits = await self.search_backend.knn_search(
                embedding,
                k=dense_k,
                group_id=group_id,
            )
            latency["dense_ms"] = (time.perf_counter() - t0) * 1000
            RETRIEVAL_LATENCY.labels(stage="dense").observe(latency["dense_ms"] / 1000)

            if mode == SearchMode.DENSE:
                hits = dense_hits

        if mode in (SearchMode.SPARSE, SearchMode.HYBRID):
            t0 = time.perf_counter()
            sparse_hits = await self.search_backend.bm25_search(
                query,
                k=sparse_k,
                group_id=group_id,
            )
            latency["sparse_ms"] = (time.perf_counter() - t0) * 1000
            RETRIEVAL_LATENCY.labels(stage="sparse").observe(latency["sparse_ms"] / 1000)

            if mode == SearchMode.SPARSE:
                hits = sparse_hits

        if mode == SearchMode.HYBRID:
            t0 = time.perf_counter()
            hits = rrf_fuse(dense_hits, sparse_hits, k=self.config.get("rrf_k", 60))
            latency["fusion_ms"] = (time.perf_counter() - t0) * 1000
            RETRIEVAL_LATENCY.labels(stage="fusion").observe(latency["fusion_ms"] / 1000)

        if rerank and hits:
            t0 = time.perf_counter()
            hits = self.reranker_service.rerank(query, hits[:rerank_input_k], top_n=rerank_top_n)
            latency["rerank_ms"] = (time.perf_counter() - t0) * 1000
            RETRIEVAL_LATENCY.labels(stage="rerank").observe(latency["rerank_ms"] / 1000)
        else:
            hits = hits[:rerank_top_n]

        if expand_to_parent:
            hits = self._expand_to_parent(hits)

        citations = self._to_citations(hits, expand_to_parent=expand_to_parent)
        latency["total_ms"] = sum(latency.values())
        return citations, latency

    async def _get_query_embedding(self, query: str) -> list[float]:
        cached = await self.embedding_cache.get(query, self.embedding_service.model_name)
        if cached:
            return cached

        embedding = self.embedding_service.embed_query(query)
        await self.embedding_cache.set(query, self.embedding_service.model_name, embedding)
        return embedding

    @staticmethod
    def _expand_to_parent(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep one hit per parent (highest score), preserving first-seen order."""
        best_by_key: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        for hit in hits:
            parent_id = hit.get("parent_chunk_id")
            key = parent_id or str(hit.get("chunk_id", ""))
            score = float(
                hit.get("rerank_score", hit.get("rrf_score", hit.get("score", 0.0)))
            )
            existing = best_by_key.get(key)
            if existing is None:
                best_by_key[key] = hit
                order.append(key)
                continue
            existing_score = float(
                existing.get(
                    "rerank_score",
                    existing.get("rrf_score", existing.get("score", 0.0)),
                )
            )
            if score > existing_score:
                best_by_key[key] = hit

        return [best_by_key[key] for key in order]

    @staticmethod
    def _to_citations(
        hits: list[dict[str, Any]],
        *,
        expand_to_parent: bool,
    ) -> list[Citation]:
        citations = []
        for rank, hit in enumerate(hits, start=1):
            score = hit.get("rerank_score", hit.get("rrf_score", hit.get("score", 0.0)))
            child_content = hit.get("content", "") or ""
            if expand_to_parent:
                body = hit.get("parent_content") or child_content
            else:
                body = child_content
            snippet = child_content[:300] + ("..." if len(child_content) > 300 else "")
            citations.append(
                Citation(
                    chunk_id=str(hit.get("chunk_id", "")),
                    doc_id=str(hit.get("doc_id", "")),
                    filename=hit.get("filename", ""),
                    page=hit.get("page"),
                    score=float(score),
                    snippet=snippet,
                    rank=rank,
                    content=body,
                )
            )
        return citations

    async def close(self) -> None:
        await self.search_backend.close()
