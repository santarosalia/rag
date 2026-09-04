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
    # Single data row → no row-split; original table only (HTML→MD).
    table = "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
    items = [
        _item(item_type="paragraph_title", markdown="### 표"),
        _item(item_type="table", markdown=table),
    ]
    chunks = results_to_chunks(items, max_tokens=512)
    assert len(chunks) == 1
    assert "### 표" in chunks[0].content
    assert "| a | b |" in chunks[0].content
    assert "<table" not in chunks[0].content
    assert chunks[0].type == "table"
    assert chunks[0].page == 1
    assert chunks[0].bbox is not None
    assert chunks[0].bbox["coord_origin"] == "TOPLEFT"


def test_pipe_table_emits_original_plus_row_chunks():
    table = (
        "| 항목 | 값 |\n"
        "| --- | --- |\n"
        "| 담당 | 홍길동 |\n"
        "| 기간 | 3개월 |"
    )
    items = [_item(item_type="table", markdown=table)]
    chunks = results_to_chunks(items, max_tokens=512)
    assert len(chunks) == 3  # original + 2 rows
    assert chunks[0].type == "table"
    assert chunks[0].content == table
    rows = [c for c in chunks if c.type == "table_row"]
    assert len(rows) == 2
    assert rows[0].content == "| 항목 | 값 |\n| 담당 | 홍길동 |"
    assert rows[1].content == "| 항목 | 값 |\n| 기간 | 3개월 |"
    assert all(c.page == 1 and c.bbox is not None for c in rows)


def test_pipe_table_single_data_row_does_not_split():
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    chunks = results_to_chunks([_item(item_type="table", markdown=table)])
    assert len(chunks) == 1
    assert chunks[0].type == "table"


def test_html_table_emits_original_plus_row_chunks():
    table = (
        "<table>"
        "<tr><th>항목</th><th>값</th></tr>"
        "<tr><td>담당</td><td>홍길동</td></tr>"
        "<tr><td>기간</td><td>3개월</td></tr>"
        "</table>"
    )
    chunks = results_to_chunks([_item(item_type="table", markdown=table)])
    assert len(chunks) == 3
    assert chunks[0].type == "table"
    assert chunks[0].content.startswith("|")
    assert "<table" not in chunks[0].content
    rows = [c for c in chunks if c.type == "table_row"]
    assert len(rows) == 2
    assert rows[0].content == "| 항목 | 값 |\n| 담당 | 홍길동 |"
    assert rows[1].content == "| 항목 | 값 |\n| 기간 | 3개월 |"


def test_rowspan_html_table_fills_cells_and_splits_rows():
    table = (
        "<table>"
        "<tr><td>구분</td><td>소속</td><td>성명</td></tr>"
        '<tr><td rowspan="3">내부</td><td>인사팀</td><td>박정수</td></tr>'
        "<tr><td>BIZ혁신팀</td><td>오명진</td></tr>"
        "<tr><td>영업정책팀</td><td>박세진</td></tr>"
        '<tr><td rowspan="2">외부</td><td>자활원</td><td>박수민</td></tr>'
        "<tr><td>무역보험</td><td>이승율</td></tr>"
        "</table>"
    )
    chunks = results_to_chunks([_item(item_type="table", markdown=table)])
    assert chunks[0].type == "table"
    assert "<td" not in chunks[0].content
    rows = [c for c in chunks if c.type == "table_row"]
    assert len(rows) == 5
    assert "내부" in rows[1].content and "오명진" in rows[1].content
    assert "외부" in rows[4].content and "이승율" in rows[4].content


def test_heading_prefixes_only_original_table_not_rows():
    table = (
        "| 항목 | 값 |\n"
        "| --- | --- |\n"
        "| 담당 | 홍길동 |\n"
        "| 기간 | 3개월 |"
    )
    items = [
        _item(item_type="paragraph_title", markdown="### 메타"),
        _item(item_type="table", markdown=table),
    ]
    chunks = results_to_chunks(items)
    assert chunks[0].type == "table"
    assert chunks[0].content.startswith("### 메타")
    for row in chunks[1:]:
        assert row.type == "table_row"
        assert not row.content.startswith("### 메타")


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
