from rag.ingestion.parsers import HTMLParser, MarkdownParser, PDFParser, TextParser, get_parser


def test_text_parser():
    parser = TextParser()
    doc = parser.parse(b"Hello world", "test.txt")
    assert doc.pages[0].content == "Hello world"
    assert doc.content_type == "text/plain"


def test_markdown_parser():
    parser = MarkdownParser()
    doc = parser.parse(b"# Title\n\nContent here.", "readme.md")
    assert "Title" in doc.pages[0].content


def test_html_parser_strips_scripts():
    parser = HTMLParser()
    html = b"<html><head><script>alert(1)</script></head><body><p>Hello</p></body></html>"
    doc = parser.parse(html, "page.html")
    assert "Hello" in doc.pages[0].content
    assert "alert" not in doc.pages[0].content


def test_get_parser_by_extension():
    assert isinstance(get_parser("doc.pdf"), PDFParser)
    assert isinstance(get_parser("doc.txt"), TextParser)
    assert isinstance(get_parser("unknown.xyz"), TextParser)
