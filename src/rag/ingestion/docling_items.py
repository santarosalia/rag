from __future__ import annotations

import json
from typing import Any

import tiktoken

from rag.ingestion.chunker import TextChunk

HEADING_TYPES = frozenset({"doc_title", "paragraph_title", "section_header"})
SKIP_TYPES = frozenset({"number"})


def load_docling_items(data: bytes) -> list[dict[str, Any]]:
    """Parse a Docling layout JSON array from bytes."""
    payload = json.loads(data.decode("utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("Docling JSON must be a top-level array of items")
    return payload


def items_to_chunks(
    items: list[dict[str, Any]],
    *,
    max_tokens: int = 768,
    overlap_tokens: int = 128,
    encoding_name: str = "cl100k_base",
) -> list[TextChunk]:
    """Convert Docling layout items to one search chunk per embeddable item.

    Headings are not embedded alone; the latest heading prefixes the next body
    item. Page numbers come from ``prov[0].page_no``. ``number`` items and empty
    markdown are skipped. Oversized bodies are split with token overlap only
    within that single item.
    """
    try:
        encoding = tiktoken.get_encoding(encoding_name)
    except Exception:
        encoding = tiktoken.get_encoding("cl100k_base")

    overlap_tokens = min(overlap_tokens, max(0, max_tokens - 1))
    last_heading: str | None = None
    chunks: list[TextChunk] = []
    chunk_index = 0

    for item in items:
        item_type = str(item.get("type") or "")
        markdown = str(item.get("markdown") or "").strip()
        if item_type in SKIP_TYPES or not markdown:
            continue
        if item_type in HEADING_TYPES:
            last_heading = markdown
            continue

        body = markdown
        if last_heading:
            body = f"{last_heading}\n\n{markdown}"

        page = _page_no(item)
        for piece in _split_if_needed(body, encoding, max_tokens, overlap_tokens):
            token_count = len(encoding.encode(piece))
            chunks.append(
                TextChunk(
                    content=piece,
                    chunk_index=chunk_index,
                    page=page,
                    token_count=token_count,
                )
            )
            chunk_index += 1

    return chunks


def _page_no(item: dict[str, Any]) -> int | None:
    prov = item.get("prov") or []
    if not prov or not isinstance(prov[0], dict):
        return None
    page = prov[0].get("page_no")
    return int(page) if isinstance(page, int) else None


def _split_if_needed(
    text: str,
    encoding: tiktoken.Encoding,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    token_ids = encoding.encode(text)
    if len(token_ids) <= max_tokens:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        pieces.append(encoding.decode(token_ids[start:end]))
        if end >= len(token_ids):
            break
        start = max(end - overlap_tokens, start + 1)
    return pieces
