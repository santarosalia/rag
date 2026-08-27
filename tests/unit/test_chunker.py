from rag.ingestion.chunker import SemanticChunker


def test_chunker_splits_long_text():
    chunker = SemanticChunker(max_tokens=50, overlap_tokens=10, min_chunk_tokens=5)
    text = "First paragraph with some content.\n\n" * 20
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.content
        assert chunk.token_count > 0


def test_chunker_empty_text():
    chunker = SemanticChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_chunker_preserves_short_text():
    chunker = SemanticChunker(max_tokens=512, min_chunk_tokens=1)
    text = "Short single paragraph."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].content == text


def test_chunker_breaks_at_heading_when_over_budget():
    chunker = SemanticChunker(max_tokens=40, overlap_tokens=0, min_chunk_tokens=1)
    text = "# First\n\n" + ("word " * 80) + "\n\n# Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("# Second" in c.content for c in chunks)


def test_chunker_keeps_markdown_table_in_one_chunk():
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    text = f"# T\n\n{table}"
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "| a | b |" in chunks[0].content
    assert "| 3 | 4 |" in chunks[0].content
