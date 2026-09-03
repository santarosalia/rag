import httpx
import pytest

from rag.ingestion.parser_client import ParserClient, ParserError
from rag.models.parse import ParseResponse


@pytest.mark.asyncio
async def test_parser_client_success(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "status": "SUCCESS",
                "results": [{"id": "a", "type": "text", "markdown": "hi", "prov": []}],
                "pages": {},
                "rendered_document": "# hi",
                "processing_time_ms": 12.5,
                "error": None,
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, params=None, files=None):
            assert url.endswith("/parse")
            assert params == {"output_format": "markdown"}
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    parsed = await ParserClient(base_url="http://parser.test").parse(
        b"%PDF", filename="a.pdf", output_format="markdown"
    )
    assert isinstance(parsed, ParseResponse)
    assert parsed.status == "SUCCESS"
    assert parsed.markdown_text() == "# hi"


@pytest.mark.asyncio
async def test_parser_client_http_error(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "boom"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(ParserError, match="HTTP 500"):
        await ParserClient(base_url="http://parser.test").parse(b"x", filename="a.pdf")
