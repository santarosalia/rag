from rag.indexing.pgvector_backend import PgVectorBackend

_backend: PgVectorBackend | None = None


def get_search_backend() -> PgVectorBackend:
    global _backend
    if _backend is None:
        _backend = PgVectorBackend()
    return _backend
