from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import fitz  # pymupdf
from bs4 import BeautifulSoup


@dataclass
class ParsedPage:
    content: str
    page: int | None = None


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    filename: str
    content_type: str


class BaseParser(ABC):
    @abstractmethod
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        pass


class TextParser(BaseParser):
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        content = data.decode("utf-8", errors="replace")
        return ParsedDocument(
            pages=[ParsedPage(content=content, page=None)],
            filename=filename,
            content_type="text/plain",
        )


class MarkdownParser(BaseParser):
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        content = data.decode("utf-8", errors="replace")
        return ParsedDocument(
            pages=[ParsedPage(content=content, page=None)],
            filename=filename,
            content_type="text/markdown",
        )


class HTMLParser(BaseParser):
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        soup = BeautifulSoup(data, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        content = soup.get_text(separator="\n\n", strip=True)
        return ParsedDocument(
            pages=[ParsedPage(content=content, page=None)],
            filename=filename,
            content_type="text/html",
        )


class PDFParser(BaseParser):
    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        doc = fitz.open(stream=data, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                pages.append(ParsedPage(content=text.strip(), page=i + 1))
        doc.close()

        if not pages:
            pages = [ParsedPage(content="", page=1)]

        return ParsedDocument(
            pages=pages,
            filename=filename,
            content_type="application/pdf",
        )


PARSERS: dict[str, BaseParser] = {
    ".txt": TextParser(),
    ".md": MarkdownParser(),
    ".markdown": MarkdownParser(),
    ".html": HTMLParser(),
    ".htm": HTMLParser(),
    ".pdf": PDFParser(),
}


def get_parser(filename: str) -> BaseParser:
    suffix = Path(filename).suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        return TextParser()
    return parser
