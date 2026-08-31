from rag.ingestion.chunker import MarkdownChunker


def test_chunker_empty_text():
    chunker = MarkdownChunker()
    assert chunker.chunk("") == []
    assert chunker.chunk("   ") == []


def test_chunker_preserves_short_text():
    chunker = MarkdownChunker(max_tokens=512, overlap_tokens=0, min_chunk_tokens=1)
    text = "Short single paragraph."
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "Short single paragraph." in chunks[0].content
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count > 0


def test_chunker_splits_long_text():
    chunker = MarkdownChunker(max_tokens=50, overlap_tokens=10, min_chunk_tokens=5)
    text = "First paragraph with some content.\n\n" * 20
    chunks = chunker.chunk(text)
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.content
        assert chunk.token_count > 0
        assert chunk.chunk_index == i


def test_chunker_breaks_at_heading_when_over_budget():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0, min_chunk_tokens=1)
    text = "# First\n\n" + ("word " * 80) + "\n\n# Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("Second" in c.content for c in chunks)


def test_chunker_breaks_at_h4_when_over_budget():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0, min_chunk_tokens=1)
    text = "#### First\n\n" + ("word " * 80) + "\n\n#### Second\n\nshort tail"
    chunks = chunker.chunk(text)
    assert any("First" in c.content and "Second" not in c.content for c in chunks)
    assert any("Second" in c.content for c in chunks)


def test_chunk_index_is_contiguous():
    chunker = MarkdownChunker(max_tokens=40, overlap_tokens=0, min_chunk_tokens=1)
    text = "# A\n\n" + ("word " * 80) + "\n\n# B\n\n" + ("tail " * 80)
    chunks = chunker.chunk(text)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_prose_and_table_share_chunk_when_under_budget():
    """C01-style: background prose + expectation table stay together."""
    chunker = MarkdownChunker(max_tokens=768, overlap_tokens=0, min_chunk_tokens=1)
    prose = (
        "이용 이유는 지능정보 서비스 운영의 복합성 증가, "
        "운영 이슈·히스토리 및 업체 간 형상관리 내역 공유의 어려움 때문이다."
    )
    table = (
        "| 구분 | 내용 |\n"
        "| --- | --- |\n"
        "| 기대효과 | AiSAC 서비스 품질 제고, 인수인계 시간 최소화 |"
    )
    text = f"# 이용계획\n\n{prose}\n\n# 기대 효과\n\n{table}"
    chunks = chunker.chunk(text)
    joined = "\n\n".join(c.content for c in chunks)
    assert "복합성" in joined
    assert "기대효과" in joined or "품질 제고" in joined
    assert any(
        "복합성" in c.content and ("기대효과" in c.content or "품질 제고" in c.content)
        for c in chunks
    )


def test_large_pipe_table_stays_atomic_when_alone():
    chunker = MarkdownChunker(max_tokens=30, overlap_tokens=0, min_chunk_tokens=1)
    # Many rows so table alone exceeds 30 tokens
    rows = "\n".join(f"| {i} | value{i} value{i} |" for i in range(20))
    table = f"| a | b |\n| --- | --- |\n{rows}"
    chunks = chunker.chunk(table)
    assert len(chunks) == 1
    assert "| a | b |" in chunks[0].content
    assert "| 19 | value19" in chunks[0].content


def test_chunker_keeps_fenced_code_atomic():
    chunker = MarkdownChunker(max_tokens=20, overlap_tokens=0, min_chunk_tokens=1)
    fence = "```python\nprint(1)\n\nprint(2)\n```"
    chunks = chunker.chunk(f"# T\n\n{fence}\n\nafter")
    code_chunks = [c for c in chunks if "print(1)" in c.content]
    assert len(code_chunks) == 1
    assert "print(2)" in code_chunks[0].content


def _fill(chunker: MarkdownChunker, at_least: int, at_most: int) -> str:
    words = ["alpha"]
    while chunker.count_tokens(" ".join(words)) < at_least:
        words.append("alpha")
    text = " ".join(words)
    assert chunker.count_tokens(text) <= at_most
    return text


def test_short_body_appends_to_previous_chunk():
    chunker = MarkdownChunker(max_tokens=50, overlap_tokens=0, min_chunk_tokens=20)
    first = _fill(chunker, 50, 50)
    tail = "Done."
    assert chunker.count_tokens(tail) < 20
    assert chunker.count_tokens(f"{first}\n\n{tail}") > 50
    chunks = chunker.chunk(f"{first}\n\n{tail}")
    assert len(chunks) == 1
    assert chunks[0].content.endswith(tail)
    assert first in chunks[0].content


def test_short_heading_leftover_stays_own_chunk():
    chunker = MarkdownChunker(max_tokens=50, overlap_tokens=0, min_chunk_tokens=20)
    first = _fill(chunker, 50, 50)
    leftover = "# Next\n\nHi"
    assert chunker.count_tokens(leftover) < 20
    assert chunker.count_tokens(f"{first}\n\n{leftover}") > 50
    chunks = chunker.chunk(f"{first}\n\n{leftover}")
    assert len(chunks) == 2
    assert leftover in chunks[1].content or (
        "# Next" in chunks[1].content and "Hi" in chunks[1].content
    )
    assert "# Next" not in chunks[0].content


def test_small_table_colocates_with_body():
    chunker = MarkdownChunker(max_tokens=768, overlap_tokens=0, min_chunk_tokens=1)
    meta = (
        "| 항목 | 내용 |\n"
        "| --- | --- |\n"
        "| 담당자 | 장현진 |\n"
        "| 비공개 | 비공개(5) |"
    )
    body = "AiSAC 시스템 통합 유지관리 용역을 추진한다."
    chunks = chunker.chunk(f"{meta}\n\n{body}")
    assert any("장현진" in c.content and "용역" in c.content for c in chunks)


def test_short_trailing_chunk_merges_into_previous():
    chunker = MarkdownChunker(max_tokens=768, overlap_tokens=0, min_chunk_tokens=64)
    body = "본문 내용이 여기에 있습니다. " * 5
    footer = "시행번호: 디지털혁신센터-104\n담당자: 홍길동\n비공개(5)"
    chunks = chunker.chunk(f"{body}\n\n{footer}")
    assert any("디지털혁신센터-104" in c.content and "본문 내용" in c.content for c in chunks)
