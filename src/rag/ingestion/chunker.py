from dataclasses import dataclass

import tiktoken
from llama_index.core.node_parser import MarkdownElementNodeParser, SentenceSplitter

_ATOMIC_ELEMENT_TYPES = frozenset({"table", "table_text", "code"})


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0


class MarkdownChunker:
    """Markdown → MarkdownElementNodeParser → TextChunk list.

    Tables and code fences stay atomic; body text uses SentenceSplitter.
    No LLM table summaries — flat ``content`` only for our PG contract.
    """

    def __init__(
        self,
        max_tokens: int = 768,
        overlap_tokens: int = 128,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")

        self._element_parser = MarkdownElementNodeParser(
            llm=None,
            include_metadata=False,
            include_prev_next_rel=False,
            show_progress=False,
        )
        self._sentence_splitter = SentenceSplitter(
            chunk_size=max_tokens,
            chunk_overlap=overlap_tokens,
            tokenizer=self.encoding.encode,
            include_metadata=False,
            include_prev_next_rel=False,
        )

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, page: int | None = None) -> list[TextChunk]:
        text = text.strip()
        if not text:
            return []

        # Avoid get_nodes_from_documents — that calls LLM table summaries.
        elements = self._element_parser.extract_elements(
            text,
            table_filters=[self._element_parser.filter_table],
        )
        elements = self._element_parser.extract_html_tables(elements)

        pieces: list[str] = []
        pending_heading: str | None = None

        for element in elements:
            if element.type == "title":
                level = getattr(element, "title_level", None) or 1
                level = max(1, min(int(level), 6))
                pending_heading = f"{'#' * level} {str(element.element).strip()}".strip()
                continue

            body = str(element.element).strip()
            if not body:
                continue

            if element.type in _ATOMIC_ELEMENT_TYPES:
                content = body
                if element.type == "code" and not body.lstrip().startswith("```"):
                    content = f"```\n{body}\n```"
                if pending_heading:
                    content = f"{pending_heading}\n\n{content}"
                    pending_heading = None
                pieces.append(content)
                continue

            if pending_heading:
                body = f"{pending_heading}\n\n{body}"
                pending_heading = None
            pieces.extend(self._sentence_splitter.split_text(body))

        if pending_heading:
            pieces.append(pending_heading)

        return self._to_chunks(pieces, page)

    def _to_chunks(self, pieces: list[str], page: int | None) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        for piece in pieces:
            content = piece.strip()
            if not content:
                continue
            chunks.append(
                TextChunk(
                    content=content,
                    chunk_index=len(chunks),
                    page=page,
                    token_count=self.count_tokens(content),
                )
            )
        return chunks
