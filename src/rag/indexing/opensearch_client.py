import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensearchpy import AsyncOpenSearch, helpers
from tenacity import retry, stop_after_attempt, wait_exponential

from rag.config import get_settings
from rag.observability.logging import get_logger
from rag.observability.metrics import OPENSEARCH_ERRORS

logger = get_logger(__name__)


class OpenSearchBackend:
    def __init__(self) -> None:
        settings = get_settings()
        config = settings.yaml_config.get("opensearch", {})
        self.index_alias = config.get("index_alias", "rag-chunks")
        self.index_prefix = config.get("index_prefix", "rag-chunks-v")
        self.current_index = f"{self.index_prefix}1"

        auth = None
        if settings.opensearch_user and settings.opensearch_password:
            auth = (settings.opensearch_user, settings.opensearch_password)

        self.client = AsyncOpenSearch(
            hosts=[settings.opensearch_url],
            http_auth=auth,
            use_ssl=settings.opensearch_url.startswith("https"),
            verify_certs=False,
            ssl_show_warn=False,
        )

    @property
    def name(self) -> str:
        return "opensearch"

    async def close(self) -> None:
        await self.client.close()

    async def ping(self) -> bool:
        try:
            return await self.client.ping()
        except Exception:
            return False

    async def ensure_index(self) -> None:
        template_path = Path("configs/opensearch/index_template.json")
        template = json.loads(template_path.read_text(encoding="utf-8"))

        settings_cfg = get_settings().yaml_config.get("opensearch", {})
        template["settings"]["index"]["number_of_shards"] = settings_cfg.get("number_of_shards", 1)
        template["settings"]["index"]["number_of_replicas"] = settings_cfg.get(
            "number_of_replicas", 0
        )

        exists = await self.client.indices.exists(index=self.current_index)
        if not exists:
            await self.client.indices.create(index=self.current_index, body=template)
            logger.info("opensearch_index_created", index=self.current_index)

        alias_exists = await self.client.indices.exists_alias(name=self.index_alias)
        if not alias_exists:
            await self.client.indices.put_alias(index=self.current_index, name=self.index_alias)
            logger.info(
                "opensearch_alias_created",
                alias=self.index_alias,
                index=self.current_index,
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def bulk_index(self, documents: list[dict[str, Any]]) -> tuple[int, int]:
        if not documents:
            return 0, 0

        actions = [
            {
                "_index": self.index_alias,
                "_id": doc["chunk_id"],
                "_source": doc,
            }
            for doc in documents
        ]

        success, errors = await helpers.async_bulk(
            self.client,
            actions,
            raise_on_error=False,
            refresh="wait_for",
        )

        if errors:
            OPENSEARCH_ERRORS.labels(operation="bulk_index").inc(len(errors))
            logger.warning("opensearch_bulk_partial_failure", error_count=len(errors))

        return success, len(errors) if errors else 0

    async def delete_by_doc_id(self, doc_id: str) -> int:
        try:
            response = await self.client.delete_by_query(
                index=self.index_alias,
                body={"query": {"term": {"doc_id": doc_id}}},
                refresh=True,
            )
            return response.get("deleted", 0)
        except Exception as e:
            OPENSEARCH_ERRORS.labels(operation="delete_by_query").inc()
            logger.error("opensearch_delete_failed", doc_id=doc_id, error=str(e))
            raise

    async def knn_search(
        self,
        embedding: list[float],
        k: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {
            "size": k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": embedding,
                        "k": k,
                    }
                }
            },
        }
        if tenant_id:
            query["query"] = {
                "bool": {
                    "must": [query["query"]],
                    "filter": [{"term": {"tenant_id": tenant_id}}],
                }
            }

        try:
            response = await self.client.search(index=self.index_alias, body=query)
            return self._parse_hits(response, score_key="_score")
        except Exception as e:
            OPENSEARCH_ERRORS.labels(operation="knn_search").inc()
            logger.error("opensearch_knn_search_failed", error=str(e))
            raise

    async def bm25_search(
        self,
        query_text: str,
        k: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        must_clauses: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": query_text,
                    "fields": ["content^3", "content.english^2", "content.standard"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        ]

        body: dict[str, Any] = {
            "size": k,
            "query": {"bool": {"must": must_clauses}},
        }

        if tenant_id:
            body["query"]["bool"]["filter"] = [{"term": {"tenant_id": tenant_id}}]

        try:
            response = await self.client.search(index=self.index_alias, body=body)
            return self._parse_hits(response, score_key="_score")
        except Exception as e:
            OPENSEARCH_ERRORS.labels(operation="bm25_search").inc()
            logger.error("opensearch_bm25_search_failed", error=str(e))
            raise

    @staticmethod
    def _parse_hits(response: dict[str, Any], score_key: str = "_score") -> list[dict[str, Any]]:
        hits = []
        for rank, hit in enumerate(response.get("hits", {}).get("hits", []), start=1):
            source = hit.get("_source", {})
            hits.append(
                {
                    "chunk_id": source.get("chunk_id", hit.get("_id")),
                    "doc_id": source.get("doc_id"),
                    "content": source.get("content", ""),
                    "source": source.get("source", ""),
                    "filename": source.get("filename", ""),
                    "page": source.get("page"),
                    "score": hit.get(score_key, 0.0),
                    "rank": rank,
                }
            )
        return hits


# Backward-compatible alias
OpenSearchClient = OpenSearchBackend


def build_index_document(
    chunk_id: str,
    doc_id: str,
    content: str,
    embedding: list[float],
    *,
    tenant_id: str | None = None,
    source: str = "",
    filename: str = "",
    page: int | None = None,
    chunk_index: int = 0,
    token_count: int = 0,
    content_hash: str = "",
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "tenant_id": tenant_id or "default",
        "content": content,
        "embedding": embedding,
        "source": source,
        "filename": filename,
        "page": page,
        "chunk_index": chunk_index,
        "token_count": token_count,
        "content_hash": content_hash or hashlib.sha256(content.encode()).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
    }
