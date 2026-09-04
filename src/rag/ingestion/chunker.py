"""Ingest chunk DTO. Layout splitting lives in ``parse_items``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0
    type: str | None = None
    bbox: dict | None = None
    # False → DB에는 두지만 dense/FTS 인덱스 제외 (표 원본 등)
    searchable: bool = True
    # table_row → 부모 table의 chunk_index (ingest 시 parent_chunk_id로 매핑)
    parent_chunk_index: int | None = None
