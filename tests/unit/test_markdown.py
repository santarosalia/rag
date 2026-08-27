from rag.ingestion.markdown import to_markdown


def test_already_markdown_is_passthrough():
    text = to_markdown(b"# Hello\n\nWorld", filename="doc.pdf", already_markdown=True)
    assert text == "# Hello\n\nWorld"


def test_plain_text_passthrough_as_markdown():
    text = to_markdown(b"Hello world", filename="test.txt", already_markdown=True)
    assert text == "Hello world"


def test_original_bytes_use_converter(monkeypatch):
    class FakeResult:
        markdown = "# Converted"

    class FakeMarkItDown:
        def convert_stream(self, stream, file_extension=None):
            assert file_extension == ".pdf"
            assert stream.read() == b"%PDF-fake"
            return FakeResult()

    monkeypatch.setattr("rag.ingestion.markdown.MarkItDown", FakeMarkItDown)
    text = to_markdown(b"%PDF-fake", filename="a.pdf", already_markdown=False)
    assert text == "# Converted"
