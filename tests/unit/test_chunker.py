from rag.ingestion.chunker import MarkdownChunker


def test_chunker_empty_text():
    chunker = MarkdownChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_chunker_preserves_short_text():
    chunker = MarkdownChunker(max_tokens=512, overlap_tokens=0)
    text = "Short single paragraph."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "Short single paragraph." in chunks[0].content
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count > 0


def test_chunker_splits_long_text():
    chunker = MarkdownChunker(max_tokens=50, overlap_tokens=10)
    text = "First paragraph with some content.\n\n" * 20
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.content
        assert chunk.token_count > 0
        assert chunk.chunk_index == i


def test_chunker_breaks_at_heading_when_over_budget():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0)
    text = "# First\n\n" + ("word " * 80) + "\n\n# Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("Second" in c.content for c in chunks)


def test_chunker_breaks_at_h4_when_over_budget():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0)
    text = "#### First\n\n" + ("word " * 80) + "\n\n#### Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("Second" in c.content for c in chunks)


def test_chunk_index_is_contiguous():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0)
    text = "# A\n\n" + ("word " * 80) + "\n\n# B\n\n" + ("tail " * 80)
    chunks = chunker.chunk(text)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunker_keeps_pipe_table_atomic():
    chunker = MarkdownChunker(max_tokens=30, overlap_tokens=0)
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    text = f"# T\n\nintro words here\n\n{table}\n\n## Next\n\ntail"
    chunks = chunker.chunk(text)
    table_chunks = [c for c in chunks if "| a | b |" in c.content]
    assert len(table_chunks) == 1
    assert "| 3 | 4 |" in table_chunks[0].content
    assert any("Next" in c.content or "tail" in c.content for c in chunks)


def test_chunker_keeps_fenced_code_atomic():
    chunker = MarkdownChunker(max_tokens=20, overlap_tokens=0)
    fence = "```python\nprint(1)\n\nprint(2)\n```"
    chunks = chunker.chunk(f"# T\n\n{fence}\n\nafter")
    code_chunks = [c for c in chunks if "print(1)" in c.content]
    assert len(code_chunks) == 1
    assert "print(2)" in code_chunks[0].content
