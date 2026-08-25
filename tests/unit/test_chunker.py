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
