import uuid

import pytest

from rag.groups.filter import group_filter_clause


def test_no_group_means_no_filter():
    sql, params = group_filter_clause(None, False, None)
    assert sql == ""
    assert params == {}


def test_direct_group_only_by_default():
    gid = uuid.uuid4()
    sql, params = group_filter_clause(gid, False, "/abc")
    assert "c.group_id = :group_id" in sql
    assert "group_path" not in sql
    assert params["group_id"] == str(gid)


def test_descendants_use_path_prefix():
    gid = uuid.uuid4()
    sql, params = group_filter_clause(gid, True, "/aaa/bbb")
    assert "c.group_path = :group_path" in sql
    assert "c.group_path LIKE :group_path_prefix" in sql
    assert params["group_path"] == "/aaa/bbb"
    assert params["group_path_prefix"] == "/aaa/bbb/%"


def test_descendants_without_path_raise():
    gid = uuid.uuid4()
    with pytest.raises(ValueError, match="group_path"):
        group_filter_clause(gid, True, None)
