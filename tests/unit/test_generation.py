from rag.generation.llm import build_context
from rag.models.schemas import Citation


def test_build_context_respects_budget():
    citations = [
        Citation(
            chunk_id="1",
            doc_id="d1",
            source="s1",
            filename="f1.txt",
            page=1,
            score=0.9,
            snippet="A" * 1000,
            rank=1,
        ),
        Citation(
            chunk_id="2",
            doc_id="d2",
            source="s2",
            filename="f2.txt",
            page=2,
            score=0.8,
            snippet="B" * 1000,
            rank=2,
        ),
    ]
    context = build_context(citations, max_tokens=100)
    assert len(context) < 1000


def test_build_context_numbering():
    citations = [
        Citation(
            chunk_id="1",
            doc_id="d1",
            source="s1",
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
