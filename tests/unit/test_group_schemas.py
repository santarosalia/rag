import pytest
from pydantic import ValidationError

from rag.models.schemas import GroupCreate, QueryRequest, RetrieveRequest


def test_retrieve_group_id_optional():
    req = RetrieveRequest(query="hello")
    assert req.group_id is None


def test_query_group_id_optional():
    req = QueryRequest(query="hello")
    assert req.group_id is None


def test_retrieve_accepts_string_group_id():
    req = RetrieveRequest(query="hello", group_id="ga")
    assert req.group_id == "ga"


def test_group_create_optional_id():
    body = GroupCreate(name="세무")
    assert body.id is None
    body = GroupCreate(id="ga", name="세무")
    assert body.id == "ga"


def test_group_create_rejects_invalid_id():
    with pytest.raises(ValidationError):
        GroupCreate(id="not valid", name="세무")
