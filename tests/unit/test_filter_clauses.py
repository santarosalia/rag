from rag.groups.filter import group_filter_clause, normalize_tags, tag_filter_clause


def test_group_filter_clause_empty():
    clause, params = group_filter_clause(None)
    assert clause == ""
    assert params == {}


def test_normalize_tags():
    assert normalize_tags(None) == []
    assert normalize_tags("  tax  ") == ["tax"]
    assert normalize_tags([" tax ", "", "hr", "tax"]) == ["tax", "hr"]


def test_tag_filter_clause_and():
    clause, params = tag_filter_clause(None)
    assert clause == ""
    assert params == {}

    clause, params = tag_filter_clause([" tax ", "hr"])
    assert clause == "AND d.tag @> ARRAY[:doc_tag_0, :doc_tag_1]::text[]"
    assert params == {"doc_tag_0": "tax", "doc_tag_1": "hr"}
