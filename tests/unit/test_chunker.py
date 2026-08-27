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


def test_chunker_breaks_at_h4_when_over_budget():
    chunker = SemanticChunker(max_tokens=40, overlap_tokens=0, min_chunk_tokens=1)
    text = "#### First\n\n" + ("word " * 80) + "\n\n#### Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("#### Second" in c.content for c in chunks)


def test_chunker_keeps_markdown_table_in_one_chunk():
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    text = f"# T\n\n{table}"
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "| a | b |" in chunks[0].content
    assert "| 3 | 4 |" in chunks[0].content


def test_chunker_keeps_fenced_code_with_blank_lines():
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    fence = "```python\nprint(1)\n\nprint(2)\n```"
    chunks = chunker.chunk(f"# T\n\n{fence}")
    assert len(chunks) == 1
    assert "print(1)" in chunks[0].content
    assert "print(2)" in chunks[0].content
    assert chunks[0].content.count("```") == 2


def test_heading_inside_fence_is_not_a_section():
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    text = "```\n# not heading\n```\n\n# Real\n\nbody"
    chunks = chunker.chunk(text)
    joined = "\n\n".join(c.content for c in chunks)
    assert "```\n# not heading\n```" in joined
    assert any("# Real" in c.content for c in chunks)


def test_chunker_keeps_html_table_with_blank_lines():
    chunker = SemanticChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    html = "<table>\n<tr>\n\n<td>a</td>\n</tr>\n</table>"
    chunks = chunker.chunk(f"# T\n\n{html}")
    assert len(chunks) == 1
    assert "<table>" in chunks[0].content
    assert "<td>a</td>" in chunks[0].content
    assert "</table>" in chunks[0].content


def test_oversized_fence_stays_one_chunk():
    chunker = SemanticChunker(max_tokens=30, overlap_tokens=0, min_chunk_tokens=1)
    text = "```\n" + ("word " * 80) + "\n```"
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].content.startswith("```")
    assert chunks[0].content.endswith("```")


def _fill(chunker: SemanticChunker, at_least: int, at_most: int) -> str:
    words = ["alpha"]
    while chunker.count_tokens(" ".join(words)) < at_least:
        words.append("alpha")
    text = " ".join(words)
    assert chunker.count_tokens(text) <= at_most
    return text


def test_short_body_appends_to_previous_chunk():
    chunker = SemanticChunker(max_tokens=50, overlap_tokens=0, min_chunk_tokens=20)
    first = _fill(chunker, 50, 50)
    tail = "Done."
    assert chunker.count_tokens(tail) < 20
    assert chunker.count_tokens(f"{first}\n\n{tail}") > 50
    chunks = chunker.chunk(f"{first}\n\n{tail}")
    assert len(chunks) == 1
    assert chunks[0].content.endswith(tail)
    assert first in chunks[0].content


def test_short_heading_leftover_stays_own_chunk():
    chunker = SemanticChunker(max_tokens=50, overlap_tokens=0, min_chunk_tokens=20)
    first = _fill(chunker, 50, 50)
    leftover = "# Next\n\nHi"
    assert chunker.count_tokens(leftover) < 20
    assert chunker.count_tokens(f"{first}\n\n{leftover}") > 50
    chunks = chunker.chunk(f"{first}\n\n{leftover}")
    assert len(chunks) == 2
    assert leftover in chunks[1].content
    assert leftover not in chunks[0].content


def test_short_h4_leftover_stays_own_chunk():
    chunker = SemanticChunker(max_tokens=50, overlap_tokens=0, min_chunk_tokens=20)
    first = _fill(chunker, 50, 50)
    leftover = "#### Note\n\nHi"
    assert chunker.count_tokens(leftover) < 20
    assert chunker.count_tokens(f"{first}\n\n{leftover}") > 50
    chunks = chunker.chunk(f"{first}\n\n{leftover}")
    assert len(chunks) == 2
    assert chunks[1].content.startswith("#### Note")
