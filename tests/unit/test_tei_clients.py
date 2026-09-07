"""TEI HTTP clients for embed / rerank (mocked)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rag.retrieval import embeddings as emb_mod


@pytest.fixture(autouse=True)
def _clear_caches():
    emb_mod.get_embedding_service.cache_clear()
    emb_mod.get_reranker_service.cache_clear()
    yield
    emb_mod.get_embedding_service.cache_clear()
    emb_mod.get_reranker_service.cache_clear()


def test_tei_embed_batches(monkeypatch):
    monkeypatch.setenv("TEI_EMBEDDING_URL", "http://tei-embed:80")
    from rag.config import get_settings

    get_settings.cache_clear()

    calls: list[dict] = []

    def fake_post(url, json=None):
        calls.append({"url": url, "json": json})
        n = len(json["inputs"])
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [[0.1] * 4 for _ in range(n)]
        return resp

    client = MagicMock()
    client.post.side_effect = fake_post

    svc = emb_mod.EmbeddingService()
    with patch.object(svc, "_http", return_value=client):
        out = svc.embed_texts(["a", "b", "c"], batch_size=2)

    assert len(out) == 3
    assert len(calls) == 2
    assert calls[0]["json"]["normalize"] is True
    assert calls[0]["json"]["inputs"] == ["a", "b"]
    assert calls[1]["json"]["inputs"] == ["c"]
    get_settings.cache_clear()


def test_tei_rerank_maps_scores_by_index(monkeypatch):
    monkeypatch.setenv("TEI_RERANKER_URL", "http://tei-rerank:80")
    from rag.config import get_settings

    get_settings.cache_clear()

    def fake_post(url, json=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [
            {"index": 1, "score": 0.9},
            {"index": 0, "score": 0.2},
        ]
        return resp

    client = MagicMock()
    client.post.side_effect = fake_post

    docs = [
        {"chunk_id": "a", "content": "low"},
        {"chunk_id": "b", "content": "high"},
    ]
    svc = emb_mod.RerankerService()
    with patch.object(svc, "_http", return_value=client):
        ranked = svc.rerank("q", docs, top_n=2)

    assert [d["chunk_id"] for d in ranked] == ["b", "a"]
    assert ranked[0]["rerank_score"] == 0.9
    get_settings.cache_clear()


def test_tei_rerank_batches(monkeypatch):
    monkeypatch.setenv("TEI_RERANKER_URL", "http://tei-rerank:80")
    from rag.config import get_settings

    get_settings.cache_clear()
    calls: list[int] = []

    def fake_post(url, json=None):
        calls.append(len(json["texts"]))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = [
            {"index": i, "score": float(len(json["texts"]) - i)} for i in range(len(json["texts"]))
        ]
        return resp

    client = MagicMock()
    client.post.side_effect = fake_post
    docs = [{"chunk_id": str(i), "content": f"c{i}"} for i in range(5)]
    svc = emb_mod.RerankerService()
    svc.batch_size = 2
    with patch.object(svc, "_http", return_value=client):
        ranked = svc.rerank("q", docs, top_n=3)

    assert calls == [2, 2, 1]
    assert len(ranked) == 3
    get_settings.cache_clear()


def test_tei_embed_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("TEI_EMBEDDING_URL", "http://tei-embed:80")
    from rag.config import get_settings

    get_settings.cache_clear()

    def fake_post(url, json=None):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        return resp

    client = MagicMock()
    client.post.side_effect = fake_post
    svc = emb_mod.EmbeddingService()
    with patch.object(svc, "_http", return_value=client):
        with pytest.raises(httpx.HTTPStatusError):
            svc.embed_texts(["x"])
    get_settings.cache_clear()
