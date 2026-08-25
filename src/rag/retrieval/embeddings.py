import hashlib
import json
from functools import lru_cache

import redis.asyncio as aioredis
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag.config import get_settings
from rag.observability.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        settings = get_settings()
        config = settings.yaml_config.get("models", {})
        self.model_name = settings.embedding_model or config.get("embedding", "BAAI/bge-m3")
        self.device = settings.embedding_device or config.get("device", "cpu")
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("loading_embedding_model", model=self.model_name, device=self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class RerankerService:
    def __init__(self) -> None:
        settings = get_settings()
        config = settings.yaml_config.get("models", {})
        self.model_name = settings.reranker_model or config.get(
            "reranker", "BAAI/bge-reranker-v2-m3"
        )
        self.device = settings.embedding_device or config.get("device", "cpu")
        self.batch_size = config.get("reranker_batch_size", 16)
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            logger.info("loading_reranker_model", model=self.model_name, device=self.device)
            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        if not documents:
            return []

        pairs = [[query, doc.get("content", "")] for doc in documents]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

        scored = []
        for doc, score in zip(documents, scores, strict=True):
            result = doc.copy()
            result["rerank_score"] = float(score)
            scored.append(result)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_n]


class QueryEmbeddingCache:
    def __init__(self) -> None:
        settings = get_settings()
        self.redis_url = settings.redis_url
        self.ttl = settings.yaml_config.get("cache", {}).get("query_embedding_ttl_seconds", 3600)
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    @staticmethod
    def _cache_key(query: str, model_name: str) -> str:
        digest = hashlib.sha256(f"{model_name}:{query}".encode()).hexdigest()
        return f"emb:{digest}"

    async def get(self, query: str, model_name: str) -> list[float] | None:
        try:
            redis = await self._get_redis()
            key = self._cache_key(query, model_name)
            cached = await redis.get(key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("embedding_cache_get_failed", error=str(e))
        return None

    async def set(self, query: str, model_name: str, embedding: list[float]) -> None:
        try:
            redis = await self._get_redis()
            key = self._cache_key(query, model_name)
            await redis.setex(key, self.ttl, json.dumps(embedding))
        except Exception as e:
            logger.warning("embedding_cache_set_failed", error=str(e))


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_reranker_service() -> RerankerService:
    return RerankerService()


@lru_cache
def get_embedding_cache() -> QueryEmbeddingCache:
    return QueryEmbeddingCache()
