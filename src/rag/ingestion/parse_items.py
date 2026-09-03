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

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


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

        content = f"{pending_heading}\n\n{md}" if pending_heading else md
        pending_heading = None
        page = _page_of(item)
        bbox = _bbox_of(item)
        item_type = item.type
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
            chunk_index += 1
            continue

        for part in _split_oversized(content, max_tokens=max_tokens, encoding=encoding):
            part = part.strip()
            if not part:
                continue
            chunks.append(
                TextChunk(
                    content=part,
                    chunk_index=chunk_index,
                    page=page,
                    token_count=len(encoding.encode(part)),
                    type=item_type,
                    bbox=bbox,
                )
            )
            chunk_index += 1

    return chunks


def parse_response_to_chunks(
    parse: ParseResponse,
    *,
    max_tokens: int = 768,
) -> list[TextChunk]:
    return results_to_chunks(parse.results, max_tokens=max_tokens)
