from functools import lru_cache

import httpx

from rag.config import get_settings
from rag.observability.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """Embed via TEI ``/embed`` when ``TEI_EMBEDDING_URL`` is set; else local ST."""

    def __init__(self) -> None:
        settings = get_settings()
        config = settings.yaml_config.get("models", {})
        self.model_name = settings.embedding_model or config.get("embedding", "BAAI/bge-m3")
        self.device = settings.embedding_device or config.get("device", "cpu")
        self.tei_url = (settings.tei_embedding_url or "").rstrip("/")
        self.timeout = settings.tei_timeout_seconds
        self._model = None
        self._client: httpx.Client | None = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("loading_embedding_model", model=self.model_name, device=self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        if not texts:
            return []
        if self.tei_url:
            return self._embed_tei(texts, batch_size=batch_size)
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def _embed_tei(self, texts: list[str], *, batch_size: int) -> list[list[float]]:
        out: list[list[float]] = []
        client = self._http()
        url = f"{self.tei_url}/embed"
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = client.post(
                url,
                json={"inputs": batch, "normalize": True},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"unexpected TEI embed response type: {type(payload)}")
            out.extend(payload)
        return out

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


class RerankerService:
    """Rerank via TEI ``/rerank`` when ``TEI_RERANKER_URL`` is set; else local CrossEncoder."""

    def __init__(self) -> None:
        settings = get_settings()
        config = settings.yaml_config.get("models", {})
        self.model_name = settings.reranker_model or config.get(
            "reranker", "BAAI/bge-reranker-v2-m3"
        )
        self.device = settings.embedding_device or config.get("device", "cpu")
        self.batch_size = config.get("reranker_batch_size", 16)
        self.tei_url = (settings.tei_reranker_url or "").rstrip("/")
        self.timeout = settings.tei_timeout_seconds
        self._model = None
        self._client: httpx.Client | None = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("loading_reranker_model", model=self.model_name, device=self.device)
            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int = 5,
    ) -> list[dict]:
        if not documents:
            return []

        if self.tei_url:
            return self._rerank_tei(query, documents, top_n=top_n)

        pairs = [[query, doc.get("content", "")] for doc in documents]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

        scored = []
        for doc, score in zip(documents, scores, strict=True):
            result = doc.copy()
            result["rerank_score"] = float(score)
            scored.append(result)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_n]

    def _rerank_tei(self, query: str, documents: list[dict], *, top_n: int) -> list[dict]:
        # TEI payload / max_client_batch_size limits — score in batches then merge.
        client = self._http()
        url = f"{self.tei_url}/rerank"
        scored: list[dict] = []
        for start in range(0, len(documents), self.batch_size):
            batch = documents[start : start + self.batch_size]
            texts = [(doc.get("content") or "")[:4000] for doc in batch]
            response = client.post(
                url,
                json={
                    "query": query,
                    "texts": texts,
                    "raw_scores": False,
                    "return_text": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"unexpected TEI rerank response type: {type(payload)}")
            for item in payload:
                idx = int(item["index"])
                result = batch[idx].copy()
                result["rerank_score"] = float(item["score"])
                scored.append(result)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_n]


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@lru_cache
def get_reranker_service() -> RerankerService:
    return RerankerService()
