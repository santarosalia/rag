import pytest

from rag.groups.filter import group_filter_clause
from rag.groups.ids import InvalidGroupId, parse_group_id, resolve_create_id


def test_no_group_means_no_filter():
    sql, params = group_filter_clause(None)
    assert sql == ""
    assert params == {}


def test_direct_group_equality():
    sql, params = group_filter_clause("ga")
    assert sql == "AND c.group_id = :group_id"
    assert params["group_id"] == "ga"


def test_parse_accepts_uuid_and_slug():
    assert parse_group_id("ga") == "ga"
    assert parse_group_id("tax-2024") == "tax-2024"
    uuid_id = "11111111-1111-4111-8111-111111111111"
    assert parse_group_id(uuid_id) == uuid_id


def test_parse_rejects_spaces_and_slashes():
    with pytest.raises(InvalidGroupId):
        parse_group_id("not valid")
    with pytest.raises(InvalidGroupId):
        parse_group_id("a/b")


def test_omitted_create_id_is_uuid_string():
    generated = resolve_create_id(None)
    assert parse_group_id(generated) == generated
    assert generated != resolve_create_id(None)
