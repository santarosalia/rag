import pytest
from pydantic import ValidationError

from rag.models.schemas import (
    Citation,
    GroupCreate,
    QueryRequest,
    RetrieveRequest,
    project_citation_bodies,
)


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
    body = GroupCreate()
    assert body.id is None
    body = GroupCreate(id="ga")
    assert body.id == "ga"


def test_group_create_rejects_invalid_id():
    with pytest.raises(ValidationError):
        GroupCreate(id="not valid")


def test_query_citation_body_defaults():
    req = QueryRequest(query="hello")
    assert req.snippet is True
    assert req.content is False


def test_project_citation_bodies_omits_unrequested_fields():
    citation = Citation(
        chunk_id="c1",
        doc_id="d1",
        filename="doc.md",
        page=2,
        score=0.9,
        snippet="preview",
        rank=1,
        content="full chunk",
    )
    snippet_only = project_citation_bodies([citation], snippet=True, content=False)
    dumped = snippet_only[0].model_dump()
    assert dumped["snippet"] == "preview"
    assert "content" not in dumped

    content_only = project_citation_bodies([citation], snippet=False, content=True)
    dumped = content_only[0].model_dump()
    assert "snippet" not in dumped
    assert dumped["content"] == "full chunk"
