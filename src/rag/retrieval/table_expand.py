"""Collapse table_row search hits into parent table context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.session import AsyncSessionLocal


def expand_table_row_hits(
    hits: list[dict[str, Any]],
    *,
    parents_by_doc_index: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace ``table_row`` hits with parent table content; dedupe by parent.

    ``parents_by_doc_index`` maps ``(doc_id, parent_chunk_index)`` →
    ``{"chunk_id", "content"}``. Rows whose parent is missing stay as-is.
    Non-row hits pass through. Rank is reassigned 1..n.
    """
    out: list[dict[str, Any]] = []
    seen_parents: set[tuple[str, int]] = set()

    for hit in hits:
        if hit.get("type") != "table_row":
            out.append(dict(hit))
            continue

        doc_id = str(hit.get("doc_id", ""))
        parent_idx = hit.get("parent_chunk_index")
        if parent_idx is None:
            out.append(dict(hit))
            continue

        key = (doc_id, int(parent_idx))
        if key in seen_parents:
            continue
        parent = parents_by_doc_index.get(key)
        if not parent:
            out.append(dict(hit))
            continue

        seen_parents.add(key)
        merged = dict(hit)
        merged["chunk_id"] = parent["chunk_id"]
        merged["content"] = parent["content"]
        merged["type"] = "table"
        merged["chunk_index"] = int(parent_idx)
        merged["parent_chunk_index"] = None
        out.append(merged)

    for rank, hit in enumerate(out, start=1):
        hit["rank"] = rank
    return out


async def attach_parent_chunk_indices(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each ``table_row`` hit, set ``parent_chunk_index`` to nearest preceding table."""
    enriched: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        for hit in hits:
            item = dict(hit)
            if item.get("type") == "table_row" and item.get("parent_chunk_index") is None:
                parent_idx = await _nearest_table_chunk_index(
                    session,
                    doc_id=str(item.get("doc_id", "")),
                    row_chunk_index=int(item.get("chunk_index") or 0),
                )
                if parent_idx is not None:
                    item["parent_chunk_index"] = parent_idx
            enriched.append(item)
    return enriched


async def load_parents_by_doc_index(
    hits: list[dict[str, Any]],
) -> dict[tuple[str, int], dict[str, Any]]:
    keys: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for hit in hits:
        if hit.get("type") != "table_row":
            continue
        parent_idx = hit.get("parent_chunk_index")
        if parent_idx is None:
            continue
        key = (str(hit.get("doc_id", "")), int(parent_idx))
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)

    if not keys:
        return {}

    parents: dict[tuple[str, int], dict[str, Any]] = {}
    async with AsyncSessionLocal() as session:
        for doc_id, parent_idx in keys:
            row = await session.execute(
                text(
                    """
                    SELECT id::text AS chunk_id, content
                    FROM chunks
                    WHERE doc_id = CAST(:doc_id AS uuid)
                      AND chunk_index = :chunk_index
                    LIMIT 1
                    """
                ),
                {"doc_id": doc_id, "chunk_index": parent_idx},
            )
            mapped = row.mappings().first()
            if mapped:
                parents[(doc_id, parent_idx)] = {
                    "chunk_id": mapped["chunk_id"],
                    "content": mapped["content"] or "",
                }
    return parents


async def expand_hits_with_parent_tables(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve parents for row hits, swap content to parent table, dedupe."""
    if not any(h.get("type") == "table_row" for h in hits):
        return hits
    with_parents = await attach_parent_chunk_indices(hits)
    parents = await load_parents_by_doc_index(with_parents)
    return expand_table_row_hits(with_parents, parents_by_doc_index=parents)


async def _nearest_table_chunk_index(
    session: AsyncSession,
    *,
    doc_id: str,
    row_chunk_index: int,
) -> int | None:
    result = await session.execute(
        text(
            """
            SELECT chunk_index
            FROM chunks
            WHERE doc_id = CAST(:doc_id AS uuid)
              AND type IN ('table', 'table_text')
              AND chunk_index < :row_chunk_index
            ORDER BY chunk_index DESC
            LIMIT 1
            """
        ),
        {"doc_id": doc_id, "row_chunk_index": row_chunk_index},
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None
