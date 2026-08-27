import re
from dataclasses import dataclass

import tiktoken

_HEADING = re.compile(r"(?m)^(?=#{1,3} )")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")


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

        chunks: list[TextChunk] = []
        current_parts: list[str] = []
        current_tokens = 0
        chunk_index = 0

        def flush() -> None:
            nonlocal current_parts, current_tokens, chunk_index
            if not current_parts:
                return
            content = "\n\n".join(current_parts).strip()
            if not content:
                current_parts = []
                current_tokens = 0
                return
            if self.count_tokens(content) >= self.min_chunk_tokens or not chunks:
                chunks.append(self._make_chunk(content, chunk_index, page))
                chunk_index += 1
            current_parts = []
            current_tokens = 0

        for section in self._split_heading_sections(text):
            for block in self._markdown_blocks(section):
                block_tokens = self.count_tokens(block)
                if self._is_table_block(block):
                    if current_tokens + block_tokens > self.max_tokens and current_parts:
                        flush()
                    current_parts.append(block)
                    current_tokens = self.count_tokens("\n\n".join(current_parts))
                    continue

                if block_tokens > self.max_tokens:
                    if current_parts:
                        overlap = self._get_overlap(current_parts)
                        flush()
                        current_parts = list(overlap)
                        current_tokens = self._parts_tokens(current_parts)
                    for sub in self._split_oversized(block):
                        if current_parts:
                            flush()
                        chunks.append(self._make_chunk(sub, chunk_index, page))
                        chunk_index += 1
                    continue

                if current_tokens + block_tokens > self.max_tokens and current_parts:
                    overlap = self._get_overlap(current_parts)
                    flush()
                    current_parts = list(overlap)
                    current_tokens = self._parts_tokens(current_parts)

                current_parts.append(block)
                current_tokens = self.count_tokens("\n\n".join(current_parts))

        if current_parts:
            content = "\n\n".join(current_parts).strip()
            if content and (self.count_tokens(content) >= self.min_chunk_tokens or not chunks):
                chunks.append(self._make_chunk(content, chunk_index, page))

        return chunks

    def _parts_tokens(self, parts: list[str]) -> int:
        if not parts:
            return 0
        return self.count_tokens("\n\n".join(parts))

    def _make_chunk(self, content: str, chunk_index: int, page: int | None) -> TextChunk:
        return TextChunk(
            content=content.strip(),
            chunk_index=chunk_index,
            page=page,
            token_count=self.count_tokens(content),
        )

    def _split_heading_sections(self, text: str) -> list[str]:
        matches = list(_HEADING.finditer(text))
        if not matches:
            return [text]
        sections: list[str] = []
        if matches[0].start() > 0:
            prefix = text[: matches[0].start()].strip()
            if prefix:
                sections.append(prefix)
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section = text[match.start() : end].strip()
            if section:
                sections.append(section)
        return sections

    def _markdown_blocks(self, section: str) -> list[str]:
        blocks: list[str] = []
        buf: list[str] = []
        in_table = False

        def flush_buf() -> None:
            nonlocal buf
            joined = "\n".join(buf).strip()
            if joined:
                blocks.append(joined)
            buf = []

        for line in section.split("\n"):
            is_table_line = bool(_TABLE_LINE.match(line))
            if is_table_line:
                if buf and not in_table:
                    flush_buf()
                in_table = True
                buf.append(line)
                continue
            if in_table:
                flush_buf()
                in_table = False
            if not line.strip():
                flush_buf()
            else:
                buf.append(line)
        flush_buf()
        return blocks

    @staticmethod
    def _is_table_block(block: str) -> bool:
        lines = [line for line in block.split("\n") if line.strip()]
        return bool(lines) and all(_TABLE_LINE.match(line) for line in lines)

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
