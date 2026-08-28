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
        assert data["citations"][0]["snippet"] == "test snippet"
        assert "content" not in data["citations"][0]


@pytest.mark.asyncio
async def test_retrieve_includes_content_when_requested(app, monkeypatch):
    from rag.models.schemas import Citation

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
                    content="full chunk body",
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
            json={"query": "test query", "mode": "hybrid", "content": True, "snippet": False},
        )
        assert response.status_code == 200
        citation = response.json()["citations"][0]
        assert citation["content"] == "full chunk body"
        assert "snippet" not in citation


@pytest.mark.asyncio
async def test_query_citation_flags(app, monkeypatch):
    from rag.models.schemas import Citation, QueryResponse

    async def mock_query(self, **kwargs):
        return QueryResponse(
            query="q",
            answer="a",
            backend="pgvector",
            citations=[
                Citation(
                    chunk_id="c1",
                    doc_id="d1",
                    filename="test.txt",
                    page=1,
                    score=0.9,
                    snippet="preview",
                    rank=1,
                    content="full chunk body",
                )
            ],
            latency_ms={"total_ms": 1.0},
        )

    class MockService:
        query = mock_query

    monkeypatch.setattr("rag.api.routes.QueryService", lambda **kw: MockService())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        defaulted = await client.post("/v1/query", json={"query": "q"})
        assert defaulted.status_code == 200
        citation = defaulted.json()["citations"][0]
        assert citation["snippet"] == "preview"
        assert "content" not in citation

        both = await client.post(
            "/v1/query",
            json={"query": "q", "snippet": True, "content": True},
        )
        citation = both.json()["citations"][0]
        assert citation["snippet"] == "preview"
        assert citation["content"] == "full chunk body"

        hidden = await client.post(
            "/v1/query",
            json={"query": "q", "include_citations": False, "content": True},
        )
        assert hidden.json()["citations"] == []
