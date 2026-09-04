"""Parent table is stored but not searchable; row hits expand to parent for context."""

from rag.ingestion.chunker import TextChunk
from rag.ingestion.parse_items import results_to_chunks
from rag.retrieval.table_expand import expand_table_row_hits


def _item(*, item_type: str, markdown: str) -> dict:
    return {
        "id": "x",
        "type": item_type,
        "markdown": markdown,
        "prov": [
            {
                "page_no": 1,
                "bbox": {"l": 0, "t": 0, "r": 1, "b": 1, "coord_origin": "TOPLEFT"},
                "charspan": [],
            }
        ],
    }


def test_split_table_marks_original_not_searchable():
    table = (
        "| 항목 | 값 |\n"
        "| --- | --- |\n"
        "| 담당 | 홍길동 |\n"
        "| 기간 | 3개월 |"
    )
    chunks = results_to_chunks([_item(item_type="table", markdown=table)])
    assert chunks[0].type == "table"
    assert chunks[0].searchable is False
    rows = [c for c in chunks if c.type == "table_row"]
    assert len(rows) == 2
    assert all(c.searchable for c in rows)
    assert all(c.parent_chunk_index == chunks[0].chunk_index for c in rows)


def test_single_row_table_remains_searchable():
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    chunks = results_to_chunks([_item(item_type="table", markdown=table)])
    assert len(chunks) == 1
    assert chunks[0].searchable is True
    assert chunks[0].parent_chunk_index is None


def test_expand_collapses_rows_to_parent_table():
    parent = TextChunk(
        content="| 항목 | 값 |\n| --- | --- |\n| 담당 | 홍길동 |\n| 기간 | 3개월 |",
        chunk_index=0,
        type="table",
        searchable=False,
    )
    hits = [
        {
            "chunk_id": "row-1",
            "doc_id": "d1",
            "content": "| 항목 | 값 |\n| 담당 | 홍길동 |",
            "filename": "a.md",
            "page": 1,
            "score": 0.9,
            "rank": 1,
            "type": "table_row",
            "chunk_index": 1,
            "parent_chunk_index": 0,
        },
        {
            "chunk_id": "row-2",
            "doc_id": "d1",
            "content": "| 항목 | 값 |\n| 기간 | 3개월 |",
            "filename": "a.md",
            "page": 1,
            "score": 0.8,
            "rank": 2,
            "type": "table_row",
            "chunk_index": 2,
            "parent_chunk_index": 0,
        },
        {
            "chunk_id": "text-1",
            "doc_id": "d1",
            "content": "본문",
            "filename": "a.md",
            "page": 1,
            "score": 0.7,
            "rank": 3,
            "type": "text",
            "chunk_index": 3,
            "parent_chunk_index": None,
        },
    ]
    parents = {("d1", 0): {"chunk_id": "parent-0", "content": parent.content}}

    expanded = expand_table_row_hits(hits, parents_by_doc_index=parents)
    assert len(expanded) == 2
    assert expanded[0]["chunk_id"] == "parent-0"
    assert expanded[0]["content"] == parent.content
    assert expanded[0]["score"] == 0.9  # best row score kept
    assert expanded[1]["chunk_id"] == "text-1"


def test_expand_keeps_row_when_parent_missing():
    hits = [
        {
            "chunk_id": "row-1",
            "doc_id": "d1",
            "content": "row only",
            "filename": "a.md",
            "page": 1,
            "score": 0.5,
            "rank": 1,
            "type": "table_row",
            "chunk_index": 1,
            "parent_chunk_index": 0,
        }
    ]
    expanded = expand_table_row_hits(hits, parents_by_doc_index={})
    assert len(expanded) == 1
    assert expanded[0]["chunk_id"] == "row-1"
