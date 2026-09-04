"""Collapse table_row search hits into parent table context via parent_chunk_id."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rag.db.session import AsyncSessionLocal


def expand_table_row_hits(
    hits: list[dict[str, Any]],
    *,
    parents_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace ``table_row`` hits with parent table content; dedupe by parent id.

    ``parents_by_id`` maps parent ``chunk_id`` → ``{"chunk_id", "content"}``.
    Rows without a resolvable parent stay as-is. Non-row hits pass through.
    Rank is reassigned 1..n.
    """
    out: list[dict[str, Any]] = []
    seen_parents: set[str] = set()

    for hit in hits:
        if hit.get("type") != "table_row":
            out.append(dict(hit))
            continue

        parent_id = hit.get("parent_chunk_id")
        if not parent_id:
            out.append(dict(hit))
            continue

        parent_key = str(parent_id)
        if parent_key in seen_parents:
            continue
        parent = parents_by_id.get(parent_key)
        if not parent:
            out.append(dict(hit))
            continue

        seen_parents.add(parent_key)
        merged = dict(hit)
        merged["chunk_id"] = parent["chunk_id"]
        merged["content"] = parent["content"]
        merged["type"] = "table"
        merged["parent_chunk_id"] = None
        out.append(merged)

    for rank, hit in enumerate(out, start=1):
        hit["rank"] = rank
    return out


async def ensure_parent_chunk_ids(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing ``parent_chunk_id`` on table_row hits (legacy rows)."""
    enriched: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        for hit in hits:
            item = dict(hit)
            if (
                item.get("type") == "table_row"
                and not item.get("parent_chunk_id")
                and item.get("doc_id")
                and item.get("chunk_index") is not None
            ):
                parent_id = await _nearest_table_chunk_id(
                    session,
                    doc_id=str(item["doc_id"]),
                    row_chunk_index=int(item["chunk_index"]),
                )
                if parent_id is not None:
                    item["parent_chunk_id"] = parent_id
            enriched.append(item)
    return enriched


async def load_parents_by_id(
    hits: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    parent_ids: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.get("type") != "table_row":
            continue
        parent_id = hit.get("parent_chunk_id")
        if not parent_id:
            continue
        key = str(parent_id)
        if key in seen:
            continue
        seen.add(key)
        parent_ids.append(key)

    if not parent_ids:
        return {}

    parents: dict[str, dict[str, Any]] = {}
    async with AsyncSessionLocal() as session:
        for parent_id in parent_ids:
            row = await session.execute(
                text(
                    """
                    SELECT id::text AS chunk_id, content
                    FROM chunks
                    WHERE id = CAST(:chunk_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"chunk_id": parent_id},
            )
            mapped = row.mappings().first()
            if mapped:
                parents[str(mapped["chunk_id"])] = {
                    "chunk_id": mapped["chunk_id"],
                    "content": mapped["content"] or "",
                }
    return parents


async def expand_hits_with_parent_tables(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve parents for row hits, swap content to parent table, dedupe."""
    if not any(h.get("type") == "table_row" for h in hits):
        return hits
    with_parents = await ensure_parent_chunk_ids(hits)
    parents = await load_parents_by_id(with_parents)
    return expand_table_row_hits(with_parents, parents_by_id=parents)


async def _nearest_table_chunk_id(
    session: AsyncSession,
    *,
    doc_id: str,
    row_chunk_index: int,
) -> str | None:
    """Legacy fallback: nearest preceding table/table_text chunk id."""
    result = await session.execute(
        text(
            """
            SELECT id::text
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
    return str(value) if value is not None else None
