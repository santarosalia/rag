from rag.models.parse import ParseResponse, ResultItem


def test_parse_response_prefers_rendered_document():
    resp = ParseResponse(
        status="SUCCESS",
        rendered_document="# Title\n\nBody",
        results=[ResultItem(id="1", type="text", markdown="ignored")],
    )
    assert resp.markdown_text() == "# Title\n\nBody"


def test_parse_response_joins_result_markdown():
    resp = ParseResponse(
        status="SUCCESS",
        results=[
            ResultItem(id="1", type="text", markdown="Hello"),
            ResultItem(id="2", type="text", markdown="World"),
        ],
    )
    assert resp.markdown_text() == "Hello\n\nWorld"


def test_parse_response_rejects_empty_markdown():
    resp = ParseResponse(status="SUCCESS", results=[])
    try:
        resp.markdown_text()
        assert False, "expected ValueError"
    except ValueError:
        pass
