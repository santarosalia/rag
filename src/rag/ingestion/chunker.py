import re
from dataclasses import dataclass

import tiktoken


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0


class SemanticChunker:
    def __init__(
        self,
        max_tokens: int = 768,
        overlap_tokens: int = 128,
        min_chunk_tokens: int = 64,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, page: int | None = None) -> list[TextChunk]:
        text = text.strip()
        if not text:
            return []

        paragraphs = self._split_paragraphs(text)
        chunks: list[TextChunk] = []
        current_parts: list[str] = []
        current_tokens = 0
        chunk_index = 0

        for para in paragraphs:
            para_tokens = self.count_tokens(para)

            if para_tokens > self.max_tokens:
                if current_parts:
                    chunks.append(self._make_chunk(" ".join(current_parts), chunk_index, page))
                    chunk_index += 1
                    current_parts = []
                    current_tokens = 0

                sub_chunks = self._split_oversized(para)
                for sub in sub_chunks:
                    chunks.append(self._make_chunk(sub, chunk_index, page))
                    chunk_index += 1
                continue

            if current_tokens + para_tokens > self.max_tokens and current_parts:
                chunks.append(self._make_chunk(" ".join(current_parts), chunk_index, page))
                chunk_index += 1
                overlap = self._get_overlap(current_parts)
                current_parts = overlap + [para] if overlap else [para]
                current_tokens = self.count_tokens(" ".join(current_parts))
            else:
                current_parts.append(para)
                current_tokens += para_tokens

        if current_parts:
            content = " ".join(current_parts)
            if self.count_tokens(content) >= self.min_chunk_tokens or not chunks:
                chunks.append(self._make_chunk(content, chunk_index, page))

        return chunks

    def _make_chunk(self, content: str, chunk_index: int, page: int | None) -> TextChunk:
        return TextChunk(
            content=content.strip(),
            chunk_index=chunk_index,
            page=page,
            token_count=self.count_tokens(content),
        )

    def _split_paragraphs(self, text: str) -> list[str]:
        parts = re.split(r"\n\s*\n+", text)
        result = []
        for part in parts:
            part = part.strip()
            if part:
                result.append(re.sub(r"\s+", " ", part))
        return result

    def _split_oversized(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?。！？])\s+", text)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            st = self.count_tokens(sentence)

            if st > self.max_tokens:
                if current:
                    chunks.append(" ".join(current))
                    current = []
                    current_tokens = 0
                words = sentence.split()
                word_chunk: list[str] = []
                word_tokens = 0
                for word in words:
                    wt = self.count_tokens(word)
                    if word_tokens + wt > self.max_tokens and word_chunk:
                        chunks.append(" ".join(word_chunk))
                        word_chunk = [word]
                        word_tokens = wt
                    else:
                        word_chunk.append(word)
                        word_tokens += wt
                if word_chunk:
                    chunks.append(" ".join(word_chunk))
                continue

            if current_tokens + st > self.max_tokens and current:
                chunks.append(" ".join(current))
                current = [sentence]
                current_tokens = st
            else:
                current.append(sentence)
                current_tokens += st

        if current:
            chunks.append(" ".join(current))
        return chunks

    def _get_overlap(self, parts: list[str]) -> list[str]:
        if not parts or self.overlap_tokens <= 0:
            return []

        overlap_parts: list[str] = []
        tokens = 0
        for part in reversed(parts):
            pt = self.count_tokens(part)
            if tokens + pt > self.overlap_tokens:
                break
            overlap_parts.insert(0, part)
            tokens += pt
        return overlap_parts
