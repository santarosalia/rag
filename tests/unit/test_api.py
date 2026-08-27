import pytest
from httpx import ASGITransport, AsyncClient

from rag.api.main import create_app
from rag.db.session import get_db


@pytest.fixture
def app():
    application = create_app()

    async def override_get_db():
        yield None

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


@pytest.mark.asyncio
async def test_upload_requires_group_id(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/documents",
            files={"file": ("a.txt", b"hello", "text/plain")},
            headers={"X-API-Key": "dev-api-key-change-me"},
        )
        assert response.status_code == 400
        assert "group_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_key_required(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/retrieve", json={"query": "test"})
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_retrieve_with_api_key(app, monkeypatch):
    from rag.models.schemas import Citation, SearchMode

    async def mock_retrieve(self, **kwargs):
        return (
            [
                Citation(
                    chunk_id="c1",
                    doc_id="d1",
                    filename="test.txt",
                    page=None,
                    score=0.95,
                    snippet="test snippet",
                    rank=1,
                )
            ],
            {"total_ms": 10.0},
        )

    class MockPipeline:
        backend_name = "pgvector"

        retrieve = mock_retrieve

    monkeypatch.setattr(
        "rag.api.routes.RetrievalPipeline",
        lambda **kw: MockPipeline(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/retrieve",
            json={"query": "test query", "mode": "hybrid"},
            headers={"X-API-Key": "dev-api-key-change-me"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == SearchMode.HYBRID
        assert data["backend"] == "pgvector"
        assert len(data["citations"]) == 1
