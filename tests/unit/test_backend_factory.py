
from rag.indexing.factory import get_search_backend


def test_get_search_backend_returns_pgvector():
    backend = get_search_backend()
    assert backend.name == "pgvector"
