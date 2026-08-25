from rag.config import get_settings
from rag.indexing.base import SearchBackend
from rag.indexing.opensearch_client import OpenSearchBackend
from rag.indexing.pgvector_backend import PgVectorBackend

_BACKENDS: dict[str, type[SearchBackend]] = {
    "opensearch": OpenSearchBackend,
    "pgvector": PgVectorBackend,
}


def get_search_backend(backend: str | None = None) -> SearchBackend:
    settings = get_settings()
    default = settings.yaml_config.get("search", {}).get("backend", settings.search_backend)
    name = (backend or default).lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown search backend: {name}. Choose from: {', '.join(_BACKENDS)}"
        )
    return cls()
