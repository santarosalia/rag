import hashlib
from datetime import UTC, datetime
from typing import Any


def build_index_document(
    chunk_id: str,
    doc_id: str,
    content: str,
    embedding: list[float],
    *,
    tenant_id: str | None = None,
    source: str = "",
    filename: str = "",
    page: int | None = None,
    chunk_index: int = 0,
    token_count: int = 0,
    content_hash: str = "",
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "tenant_id": tenant_id or "default",
        "content": content,
        "embedding": embedding,
        "source": source,
        "filename": filename,
        "page": page,
        "chunk_index": chunk_index,
        "token_count": token_count,
        "content_hash": content_hash or hashlib.sha256(content.encode()).hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
    }
