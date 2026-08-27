from uuid import uuid4

from rag.models.schemas import QueryRequest, RetrieveRequest


def test_retrieve_include_descendants_defaults_false():
    req = RetrieveRequest(query="hello")
    assert req.group_id is None
    assert req.include_descendants is False


def test_query_include_descendants_defaults_false():
    req = QueryRequest(query="hello")
    assert req.group_id is None
    assert req.include_descendants is False


def test_retrieve_accepts_group_id_and_descendants_flag():
    gid = uuid4()
    req = RetrieveRequest(query="hello", group_id=gid, include_descendants=True)
    assert req.group_id == gid
    assert req.include_descendants is True
