from dataclasses import dataclass

import tiktoken
from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0


class MarkdownChunker:
    """Markdown → heading sections → sentence/token chunks (LlamaIndex)."""

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

        self._md_parser = MarkdownNodeParser(
            include_metadata=False,
            include_prev_next_rel=False,
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

        section_nodes = self._md_parser.get_nodes_from_documents(
            [Document(text=text)],
            show_progress=False,
        )
        chunks: list[TextChunk] = []
        for section in section_nodes:
            section_text = section.get_content().strip()
            if not section_text:
                continue
            for piece in self._sentence_splitter.split_text(section_text):
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
