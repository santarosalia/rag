"""ParseResponse.results → TextChunk (layout-unit embedding)."""

from __future__ import annotations

import json
import re
from typing import Any

import tiktoken

from rag.ingestion.chunker import TextChunk
from rag.models.parse import ParseResponse, ResultItem

HEADING_TYPES = frozenset({"doc_title", "paragraph_title", "section_header"})
SKIP_TYPES = frozenset({"number", "header", "footer"})
TABLE_TYPES = frozenset({"table", "table_text"})

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
_PIPE_SEP = re.compile(r"^\|[\s\-:|]+\|$")
_TR_OR_TABLE = re.compile(r"<(/?)(tr|table)\b[^>]*>", re.IGNORECASE)
_CELL_OR_TABLE = re.compile(r"<(/?)(td|th|table)\b[^>]*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")


def load_parse_response(data: bytes | str | dict[str, Any] | list[Any]) -> ParseResponse:
    """Accept ParseResponse JSON, dict, or bare ResultItem list (material fixtures)."""
    if isinstance(data, (bytes, bytearray)):
        payload = json.loads(bytes(data).decode("utf-8-sig"))
    elif isinstance(data, str):
        payload = json.loads(data)
    else:
        payload = data

    if isinstance(payload, list):
        return ParseResponse(status="SUCCESS", results=payload)
    if isinstance(payload, dict):
        if "results" in payload or "status" in payload:
            return ParseResponse.model_validate(payload)
        raise ValueError("Parse JSON must be ParseResponse or a ResultItem array")
    raise ValueError("Unsupported parse payload type")


def _page_of(item: ResultItem) -> int | None:
    if not item.prov:
        return None
    return item.prov[0].page_no


def _bbox_of(item: ResultItem) -> dict[str, Any] | None:
    if not item.prov:
        return None
    bbox = item.prov[0].bbox
    if bbox is None:
        return None
    return bbox.model_dump(mode="json")


def _is_table_item(item_type: str, markdown: str) -> bool:
    if item_type in TABLE_TYPES:
        return True
    stripped = markdown.strip()
    if stripped.startswith("|") and "|" in stripped[1:]:
        return True
    return bool(re.search(r"<table\b", stripped, re.IGNORECASE))


def _html_row_cells(row_inner: str) -> list[str]:
    cells: list[str] = []
    table_depth = 0
    cell_start: int | None = None
    for match in _CELL_OR_TABLE.finditer(row_inner):
        closing, tag = match.group(1), match.group(2).lower()
        if tag == "table":
            table_depth += -1 if closing else 1
            continue
        if not closing:
            if cell_start is None and table_depth == 0:
                cell_start = match.end()
        elif cell_start is not None and table_depth == 0:
            raw = row_inner[cell_start : match.start()]
            text = re.sub(r"\s+", " ", _HTML_TAG.sub(" ", raw)).strip().replace("|", "\\|")
            cells.append(text)
            cell_start = None
    return cells


def _split_table_rows(content: str) -> list[str]:
    """Return row chunk bodies as ``header\\nrow`` (empty if split not useful).

    DocuOps-compatible: need at least two data rows. Supports pipe Markdown and
    outer HTML ``<tr>`` rows. Caller keeps the original table chunk separately.
    """
    content = content.strip()
    if not content:
        return []

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    pipe_lines = [line for line in lines if line.startswith("|")]
    if len(pipe_lines) >= 3:
        header = pipe_lines[0]
        data_rows = [line for line in pipe_lines[1:] if not _PIPE_SEP.match(line)]
        if len(data_rows) >= 2:
            return [f"{header}\n{row}" for row in data_rows]

    if re.search(r"<tr\b", content, re.IGNORECASE):
        row_inners: list[str] = []
        outer_table_depth = 0
        row_start: int | None = None
        row_open_depth = 0
        for match in _TR_OR_TABLE.finditer(content):
            closing, tag = match.group(1), match.group(2).lower()
            if tag == "table":
                outer_table_depth += -1 if closing else 1
                continue
            if not closing:
                if row_start is None and outer_table_depth >= 1:
                    row_start = match.end()
                    row_open_depth = outer_table_depth
            elif row_start is not None and outer_table_depth == row_open_depth:
                row_inners.append(content[row_start : match.start()])
                row_start = None

        if len(row_inners) < 2:
            return []

        has_header = bool(
            re.search(r"<th\b", row_inners[0], re.IGNORECASE)
            or re.search(r"<thead\b", content, re.IGNORECASE)
        )
        header_cells = _html_row_cells(row_inners[0])
        header_line = " | ".join(header_cells) if header_cells else ""
        body = row_inners[1:] if has_header else row_inners

        data_lines: list[str] = []
        for row_html in body:
            cells = _html_row_cells(row_html)
            if not any(cells):
                continue
            data_lines.append(" | ".join(cells))

        if len(data_lines) < 2:
            return []

        rows: list[str] = []
        for row_text in data_lines:
            if header_line and row_text != header_line:
                rows.append(f"{header_line}\n{row_text}")
            else:
                rows.append(row_text)
        return rows

    return []


def _split_oversized(text: str, *, max_tokens: int, encoding: tiktoken.Encoding) -> list[str]:
    def count(t: str) -> int:
        return len(encoding.encode(t))

    sentences = _SENTENCE_SPLIT.split(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        st = count(sentence)
        if st > max_tokens:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_tokens = 0
            words = sentence.split()
            word_chunk: list[str] = []
            word_tokens = 0
            for word in words:
                wt = count(word)
                if word_tokens + wt > max_tokens and word_chunk:
                    chunks.append(" ".join(word_chunk))
                    word_chunk = [word]
                    word_tokens = wt
                else:
                    word_chunk.append(word)
                    word_tokens += wt
            if word_chunk:
                chunks.append(" ".join(word_chunk))
            continue
        if current_tokens + st > max_tokens and current:
            chunks.append(" ".join(current))
            current = [sentence]
            current_tokens = st
        else:
            current.append(sentence)
            current_tokens += st

    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def _append_chunk(
    chunks: list[TextChunk],
    *,
    content: str,
    chunk_index: int,
    page: int | None,
    item_type: str | None,
    bbox: dict[str, Any] | None,
    encoding: tiktoken.Encoding,
    max_tokens: int,
) -> int:
    """Append one or more chunks; return next chunk_index."""
    token_count = len(encoding.encode(content))
    if token_count <= max_tokens:
        chunks.append(
            TextChunk(
                content=content,
                chunk_index=chunk_index,
                page=page,
                token_count=token_count,
                type=item_type,
                bbox=bbox,
            )
        )
        return chunk_index + 1

    next_index = chunk_index
    for part in _split_oversized(content, max_tokens=max_tokens, encoding=encoding):
        part = part.strip()
        if not part:
            continue
        chunks.append(
            TextChunk(
                content=part,
                chunk_index=next_index,
                page=page,
                token_count=len(encoding.encode(part)),
                type=item_type,
                bbox=bbox,
            )
        )
        next_index += 1
    return next_index


def results_to_chunks(
    items: list[ResultItem] | list[dict[str, Any]],
    *,
    max_tokens: int = 768,
    encoding_name: str = "cl100k_base",
) -> list[TextChunk]:
    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:
        encoding = tiktoken.get_encoding("cl100k_base")

    normalized: list[ResultItem] = []
    for raw in items:
        if isinstance(raw, ResultItem):
            normalized.append(raw)
        else:
            normalized.append(ResultItem.model_validate(raw))

    chunks: list[TextChunk] = []
    pending_heading: str | None = None
    chunk_index = 0

    for item in normalized:
        md = (item.markdown or "").strip()
        if not md:
            continue
        if item.type in SKIP_TYPES:
            continue
        if item.type in HEADING_TYPES:
            pending_heading = md
            continue

        page = _page_of(item)
        bbox = _bbox_of(item)
        item_type = item.type

        if _is_table_item(item_type, md):
            original = f"{pending_heading}\n\n{md}" if pending_heading else md
            pending_heading = None
            chunk_index = _append_chunk(
                chunks,
                content=original,
                chunk_index=chunk_index,
                page=page,
                item_type=item_type if item_type in TABLE_TYPES else "table",
                bbox=bbox,
                encoding=encoding,
                max_tokens=max_tokens,
            )
            for row_body in _split_table_rows(md):
                chunk_index = _append_chunk(
                    chunks,
                    content=row_body,
                    chunk_index=chunk_index,
                    page=page,
                    item_type="table_row",
                    bbox=bbox,
                    encoding=encoding,
                    max_tokens=max_tokens,
                )
            continue

        content = f"{pending_heading}\n\n{md}" if pending_heading else md
        pending_heading = None
        chunk_index = _append_chunk(
            chunks,
            content=content,
            chunk_index=chunk_index,
            page=page,
            item_type=item_type,
            bbox=bbox,
            encoding=encoding,
            max_tokens=max_tokens,
        )

    return chunks


def parse_response_to_chunks(
    parse: ParseResponse,
    *,
    max_tokens: int = 768,
) -> list[TextChunk]:
    return results_to_chunks(parse.results, max_tokens=max_tokens)
