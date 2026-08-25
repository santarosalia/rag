import pytest

from rag.indexing.factory import get_search_backend


def test_get_search_backend_opensearch():
    backend = get_search_backend("opensearch")
    assert backend.name == "opensearch"


def test_get_search_backend_pgvector():
    backend = get_search_backend("pgvector")
    assert backend.name == "pgvector"


def test_get_search_backend_invalid():
    with pytest.raises(ValueError, match="Unknown search backend"):
        get_search_backend("invalid")
