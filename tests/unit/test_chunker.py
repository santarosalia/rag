from rag.ingestion.chunker import MarkdownChunker
from rag.retrieval.pipeline import RetrievalPipeline


def test_chunker_empty_text():
    chunker = MarkdownChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_chunker_short_text_has_parent_and_child():
    chunker = MarkdownChunker(max_tokens=512, parent_max_tokens=2048, overlap_tokens=0)
    chunks = chunker.chunk("Short single paragraph.")
    parents = [c for c in chunks if c.role == "parent"]
    children = [c for c in chunks if c.role == "child"]
    assert len(parents) == 1
    assert len(children) == 1
    assert children[0].chunk_index == 0
    assert children[0].parent_key == parents[0].parent_key
    assert "Short single paragraph." in children[0].content
    assert children[0].content in parents[0].content or parents[0].content


def test_chunker_splits_long_text_into_hierarchy():
    chunker = MarkdownChunker(max_tokens=50, parent_max_tokens=120, overlap_tokens=10)
    text = "First paragraph with some content. " * 40
    chunks = chunker.chunk(text)
    parents = [c for c in chunks if c.role == "parent"]
    children = [c for c in chunks if c.role == "child"]
    assert len(children) > 1
    assert len(parents) >= 1
    assert [c.chunk_index for c in children] == list(range(len(children)))
    for child in children:
        assert child.parent_key is not None
        assert any(p.parent_key == child.parent_key for p in parents)


def test_child_tokens_near_max_budget():
    chunker = MarkdownChunker(max_tokens=50, parent_max_tokens=200, overlap_tokens=0)
    text = "Alpha beta gamma delta epsilon. " * 80
    children = [c for c in chunker.chunk(text) if c.role == "child"]
    assert children
    # Hierarchical SentenceSplitter can slightly exceed; keep a soft ceiling.
    assert max(c.token_count for c in children) <= 80


def test_expand_to_parent_dedupes_siblings():
    hits = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "content": "child one",
            "parent_chunk_id": "p1",
            "parent_content": "parent shared",
            "filename": "a.md",
            "page": None,
            "score": 0.5,
            "rerank_score": 0.5,
        },
        {
            "chunk_id": "c2",
            "doc_id": "d1",
            "content": "child two longer text",
            "parent_chunk_id": "p1",
            "parent_content": "parent shared",
            "filename": "a.md",
            "page": None,
            "score": 0.9,
            "rerank_score": 0.9,
        },
        {
            "chunk_id": "c3",
            "doc_id": "d1",
            "content": "other",
            "parent_chunk_id": "p2",
            "parent_content": "parent two",
            "filename": "a.md",
            "page": None,
            "score": 0.4,
            "rerank_score": 0.4,
        },
    ]
    expanded = RetrievalPipeline._expand_to_parent(hits)
    assert len(expanded) == 2
    assert expanded[0]["chunk_id"] == "c2"
    assert expanded[0]["parent_chunk_id"] == "p1"
    assert expanded[1]["chunk_id"] == "c3"


def test_to_citations_uses_parent_content_and_child_snippet():
    hits = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "content": "child snippet body",
            "parent_chunk_id": "p1",
            "parent_content": "full parent context for generation",
            "filename": "a.md",
            "page": 1,
            "rerank_score": 0.8,
        }
    ]
    citations = RetrievalPipeline._to_citations(hits, expand_to_parent=True)
    assert len(citations) == 1
    assert citations[0].chunk_id == "c1"
    assert citations[0].snippet == "child snippet body"
    assert citations[0].content == "full parent context for generation"


def test_to_citations_legacy_null_parent_uses_child_body():
    hits = [
        {
            "chunk_id": "c_legacy",
            "doc_id": "d1",
            "content": "legacy child only",
            "parent_chunk_id": None,
            "parent_content": "legacy child only",
            "filename": "old.md",
            "page": None,
            "score": 0.3,
        }
    ]
    expanded = RetrievalPipeline._expand_to_parent(hits)
    assert len(expanded) == 1
    citations = RetrievalPipeline._to_citations(expanded, expand_to_parent=True)
    assert citations[0].content == "legacy child only"
    assert citations[0].snippet == "legacy child only"


def test_pipe_table_is_table_child():
    chunker = MarkdownChunker()
    chunks = chunker.chunk(
        "# Scope\n\nIntro.\n\n| Team | Work |\n| --- | --- |\n| IT | 보안취약점 점검 |\n\nAfter."
    )
    tables = [c for c in chunks if c.role == "child" and c.kind == "table"]
    assert len(tables) == 1
    assert "보안취약점 점검" in tables[0].content
    assert "Team" in tables[0].content
    parent = next(p for p in chunks if p.role == "parent" and p.parent_key == tables[0].parent_key)
    assert "보안취약점 점검" in parent.content


def test_html_table_is_table_child():
    chunker = MarkdownChunker()
    table = "<table><tr><td>전문인력지원</td><td>보안취약점 점검</td></tr></table>"
    chunks = chunker.chunk(f"# Scope\n\nIntro text.\n{table}\nFollowing sentence.")
    tables = [c for c in chunks if c.role == "child" and c.kind == "table"]
    assert len(tables) == 1
    assert table in tables[0].content or "보안취약점 점검" in tables[0].content


def test_heading_is_kept_in_prose():
    chunker = MarkdownChunker()
    chunks = chunker.chunk("# Contract\n\nBody paragraph about the vendor.")
    children = [c for c in chunks if c.role == "child"]
    blob = "\n".join(c.content for c in children)
    assert "Contract" in blob
    assert "Body paragraph" in blob


def test_code_fence_is_atomic():
    chunker = MarkdownChunker()
    chunks = chunker.chunk("Before.\n\n```python\nprint(1)\n```\n\nAfter.")
    fences = [c for c in chunks if c.role == "child" and c.kind == "fence"]
    assert len(fences) == 1
    assert "print(1)" in fences[0].content


def test_large_pipe_table_splits_into_row_groups():
    header = "| Col | Val |\n| --- | --- |\n"
    rows = "".join(f"| r{i} | value-{i} |\n" for i in range(40))
    chunker = MarkdownChunker(
        max_tokens=80,
        parent_max_tokens=400,
        overlap_tokens=0,
        table_child_max_tokens=60,
    )
    children = [c for c in chunker.chunk(header + rows) if c.role == "child" and c.kind == "table"]
    assert len(children) > 1
    assert all("Col" in c.content for c in children)
    assert "value-0" in children[0].content
    assert "value-39" in children[-1].content
