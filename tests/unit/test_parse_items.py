from pathlib import Path

import pytest

from rag.ingestion.parse_items import load_parse_response, results_to_chunks


def _item(
    *,
    item_type: str,
    markdown: str,
    page_no: int = 1,
    bbox: dict | None = None,
) -> dict:
    prov = {"page_no": page_no, "charspan": []}
    if bbox is not None:
        prov["bbox"] = bbox
    else:
        prov["bbox"] = {
            "l": 0.0,
            "t": 0.0,
            "r": 10.0,
            "b": 10.0,
            "coord_origin": "TOPLEFT",
        }
    return {
        "id": "test-id",
        "type": item_type,
        "markdown": markdown,
        "prov": [prov],
    }


def test_heading_prefixes_next_body_item():
    items = [
        _item(item_type="paragraph_title", markdown="### 2. 추진 과제 및 대상"),
        _item(item_type="text", markdown="본문 내용"),
    ]
    chunks = results_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].content.startswith("### 2. 추진 과제 및 대상")
    assert "본문 내용" in chunks[0].content
    assert chunks[0].type == "text"


def test_headings_are_not_embedded_alone():
    items = [
        _item(item_type="doc_title", markdown="# Title"),
        _item(item_type="paragraph_title", markdown="## Sub"),
    ]
    assert results_to_chunks(items) == []


def test_skips_number_header_footer():
    items = [
        _item(item_type="number", markdown="3"),
        _item(item_type="header", markdown="page chrome"),
        _item(item_type="footer", markdown="footer"),
        _item(item_type="text", markdown="keep me"),
    ]
    chunks = results_to_chunks(items)
    assert len(chunks) == 1
    assert chunks[0].content == "keep me"


def test_table_stays_in_one_chunk_with_heading_prefix():
    table = "<table><tr><td>a</td><td>b</td></tr></table>"
    items = [
        _item(item_type="paragraph_title", markdown="### 표"),
        _item(item_type="table", markdown=table),
    ]
    chunks = results_to_chunks(items, max_tokens=512)
    assert len(chunks) == 1
    assert "### 표" in chunks[0].content
    assert table in chunks[0].content
    assert chunks[0].type == "table"
    assert chunks[0].page == 1
    assert chunks[0].bbox is not None
    assert chunks[0].bbox["coord_origin"] == "TOPLEFT"


def test_overflow_split_preserves_type_bbox():
    long_body = "Sentence one. " * 200
    items = [_item(item_type="text", markdown=long_body, page_no=4)]
    chunks = results_to_chunks(items, max_tokens=64)
    assert len(chunks) > 1
    assert all(c.type == "text" for c in chunks)
    assert all(c.page == 4 for c in chunks)
    assert all(c.bbox is not None for c in chunks)


def test_load_parse_response_array():
    raw = [_item(item_type="text", markdown="hi")]
    parse = load_parse_response(raw)
    assert parse.status == "SUCCESS"
    assert len(parse.results) == 1


def test_load_parse_response_object():
    parse = load_parse_response(
        {
            "status": "SUCCESS",
            "results": [_item(item_type="text", markdown="hi")],
        }
    )
    assert len(parse.results) == 1


@pytest.fixture
def material_items() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / "material" / "1.json"
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_material_sample_has_no_standalone_headings(material_items: list[dict]):
    heading_lines = {
        str(item.get("markdown") or "").strip()
        for item in material_items
        if item.get("type") in {"doc_title", "paragraph_title", "section_header"}
    }
    chunks = results_to_chunks(material_items)
    assert chunks
    for chunk in chunks:
        assert chunk.content.strip() not in heading_lines
        assert chunk.type not in {"number", "header", "footer"}
