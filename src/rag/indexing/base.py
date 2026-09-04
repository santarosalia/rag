from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SearchBackend(Protocol):
    """Search/index backend backed by PostgreSQL pgvector + FTS."""

    @property
    def name(self) -> str: ...

    async def close(self) -> None: ...

    async def ping(self) -> bool: ...

    async def ensure_index(self, session: Any = None) -> None: ...

    async def bulk_index(
        self, documents: list[dict[str, Any]], session: Any = None
    ) -> tuple[int, int]: ...

    async def delete_by_doc_id(self, doc_id: str, session: Any = None) -> int: ...

    async def knn_search(
        self,
        embedding: list[float],
        k: int = 50,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def fts_search(
        self,
        query_text: str,
        k: int = 50,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]: ...
