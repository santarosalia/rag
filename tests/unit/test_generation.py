from rag.generation.llm import LLMGenerator, build_context
from rag.models.schemas import Citation


def test_build_context_respects_budget():
    citations = [
        Citation(
            chunk_id="1",
            doc_id="d1",
            filename="f1.txt",
            page=1,
            score=0.9,
            snippet="A" * 1000,
            rank=1,
        ),
        Citation(
            chunk_id="2",
            doc_id="d2",
            filename="f2.txt",
            page=2,
            score=0.8,
            snippet="B" * 1000,
            rank=2,
        ),
    ]
    context = build_context(citations, max_tokens=100)
    assert "B" not in context
    assert "[1]" in context


def test_build_context_uses_full_content_not_snippet():
    citations = [
        Citation(
            chunk_id="1",
            doc_id="d1",
            filename="f1.txt",
            page=None,
            score=0.9,
            snippet="short preview",
            rank=1,
            content="full table body with the actual numbers 12345",
        ),
    ]
    context = build_context(citations, max_tokens=4096)
    assert "12345" in context
    assert "short preview" not in context
    dumped = citations[0].model_dump()
    assert dumped["content"].startswith("full table")
    assert dumped["snippet"] == "short preview"


def test_build_context_numbering():
    citations = [
        Citation(
            chunk_id="1",
            doc_id="d1",
            filename="doc.pdf",
            page=3,
            score=0.9,
            snippet="Sample content",
            rank=1,
        ),
    ]
    context = build_context(citations, max_tokens=4096)
    assert "[1]" in context
    assert "doc.pdf" in context
    assert "page 3" in context


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}]}


class _FakeClient:
    last_json: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url, headers=None, json=None):
        _FakeClient.last_json = json
        return _FakeResponse()


def test_generate_merges_extra_body_into_request(monkeypatch):
    monkeypatch.setattr("rag.generation.llm.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(
        "rag.generation.llm.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "llm_api_key": "dummy",
                "llm_base_url": "http://llm/v1",
                "yaml_config": {
                    "llm": {
                        "model": "Qwen/Qwen3.5-35B-A3B-FP8",
                        "temperature": 0.1,
                        "max_tokens": 16,
                        "extra_body": {
                            "chat_template_kwargs": {"enable_thinking": False},
                        },
                    }
                },
            },
        )(),
    )

    import asyncio

    asyncio.run(LLMGenerator().generate("q", "ctx"))
    payload = _FakeClient.last_json
    assert payload is not None
    assert payload["model"] == "Qwen/Qwen3.5-35B-A3B-FP8"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
