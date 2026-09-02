from pathlib import Path

import pytest

from rag.ingestion.docling_items import items_to_chunks, load_docling_items


def _item(
    *,
    item_type: str,
    markdown: str,
    page_no: int = 1,
) -> dict:
    return {
        "id": "test-id",
        "type": item_type,
        "markdown": markdown,
        "prov": [{"page_no": page_no}],
    }


def test_heading_prefixes_next_body_item():
    items = [
        _item(item_type="paragraph_title", markdown="### 2. 추진 과제 및 대상"),
        _item(item_type="text", markdown="본문 내용"),
    ]
    chunks = items_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].content.startswith("### 2. 추진 과제 및 대상")
    assert "본문 내용" in chunks[0].content


def test_headings_are_not_embedded_alone():
    items = [
        _item(item_type="doc_title", markdown="# 문서 제목"),
        _item(item_type="paragraph_title", markdown="### 1. 추진 목표"),
    ]
    chunks = items_to_chunks(items)
    assert chunks == []


def test_number_items_are_skipped():
    items = [
        _item(item_type="paragraph_title", markdown="### 1. 추진 목표"),
        _item(item_type="text", markdown="본문"),
        _item(item_type="number", markdown="1"),
    ]
    chunks = items_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].content.startswith("### 1. 추진 목표")
    assert chunks[0].content.endswith("본문")


def test_empty_markdown_is_skipped():
    items = [
        _item(item_type="text", markdown="   "),
        _item(item_type="text", markdown="내용"),
    ]
    chunks = items_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].content == "내용"


def test_table_stays_in_one_chunk_with_heading_prefix():
    table = "<table><tr><td>a</td><td>b</td></tr></table>"
    items = [
        _item(item_type="paragraph_title", markdown="### 표"),
        _item(item_type="table", markdown=table),
    ]
    chunks = items_to_chunks(items, max_tokens=512)
    assert len(chunks) == 1
    assert "### 표" in chunks[0].content
    assert table in chunks[0].content


def test_page_number_from_prov():
    items = [_item(item_type="text", markdown="page 3", page_no=3)]
    chunks = items_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].page == 3


def test_oversized_item_splits_with_overlap():
    long_body = "word " * 5000
    items = [_item(item_type="text", markdown=long_body)]
    chunks = items_to_chunks(items, max_tokens=64, overlap_tokens=8)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.content
        assert chunk.token_count <= 64


@pytest.fixture(scope="module")
def input_items() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / "input.json"
    return load_docling_items(path.read_bytes())


def test_input_json_produces_expected_chunk_count(input_items: list[dict]):
    chunks = items_to_chunks(input_items)
    assert 35 <= len(chunks) <= 45
    assert all(c.content.strip() for c in chunks)
    assert all(c.page is not None for c in chunks)


def test_input_json_has_no_standalone_headings(input_items: list[dict]):
    heading_lines = {
        str(item.get("markdown") or "").strip()
        for item in input_items
        if item.get("type") in {"doc_title", "paragraph_title", "section_header"}
    }
    chunks = items_to_chunks(input_items)
    for chunk in chunks:
        assert chunk.content.strip() not in heading_lines
