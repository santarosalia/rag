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
        )
        assert response.status_code == 400
        assert "group_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_parsed_rejects_blank_markdown(app):
    from uuid import uuid4

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/documents/parsed",
            json={
                "group_id": str(uuid4()),
                "filename": "a.pdf",
                "markdown": "   ",
            },
        )
        assert response.status_code == 400
        assert "markdown" in response.json()["detail"]


@pytest.mark.asyncio
async def test_parsed_requires_filename(app):
    from uuid import uuid4

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/documents/parsed",
            json={"group_id": str(uuid4()), "markdown": "# hi"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_parsed_file_requires_group_id(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/documents/parsed/file",
            files={"file": ("note.md", b"# hello", "text/markdown")},
        )
        assert response.status_code == 400
        assert "group_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_parsed_file_rejects_empty(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/documents/parsed/file",
            data={"group_id": "ga"},
            files={"file": ("note.md", b"   ", "text/markdown")},
        )
        assert response.status_code == 400
        assert "markdown" in response.json()["detail"]


@pytest.mark.asyncio
async def test_retrieve_without_auth(app, monkeypatch):
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
        )
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == SearchMode.HYBRID
        assert data["backend"] == "pgvector"
        assert len(data["citations"]) == 1
