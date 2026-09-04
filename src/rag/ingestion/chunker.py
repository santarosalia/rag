import re
from dataclasses import dataclass

import tiktoken

_HEADING = re.compile(r"(?m)^#{1,6}\s+")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE_OPEN = re.compile(r"^( {0,3})(`{3,}|~{3,})")
_HTML_TABLE_OPEN = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TABLE_CLOSE = re.compile(r"</table\s*>", re.IGNORECASE)


def _parse_fence_open(line: str) -> tuple[str, int] | None:
    match = _FENCE_OPEN.match(line)
    if not match:
        return None
    marker = match.group(2)
    return marker[0], len(marker)


def _is_fence_close(line: str, fence: tuple[str, int]) -> bool:
    char, length = fence
    pattern = rf"^( {{0,3}})({re.escape(char)}{{{length},}})[ \t]*$"
    return re.match(pattern, line) is not None


def _html_table_delta(line: str) -> int:
    return len(_HTML_TABLE_OPEN.findall(line)) - len(_HTML_TABLE_CLOSE.findall(line))


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0
    type: str | None = None
    bbox: dict | None = None
    # False → DB에는 두지만 dense/FTS 인덱스 제외 (표 원본 등)
    searchable: bool = True
    # table_row → 부모 table의 chunk_index (컨텍스트 expand용)
    parent_chunk_index: int | None = None


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
            tokens = self.count_tokens(content)
            if (
                tokens >= self.min_chunk_tokens
                or not chunks
                or _HEADING.match(content)
            ):
                chunks.append(self._make_chunk(content, chunk_index, page))
                chunk_index += 1
            else:
                prev = chunks[-1]
                chunks[-1] = self._make_chunk(
                    f"{prev.content}\n\n{content}",
                    prev.chunk_index,
                    page,
                )
            current_parts = []
            current_tokens = 0

        for section in self._split_heading_sections(text):
            for block in self._markdown_blocks(section):
                block_tokens = self.count_tokens(block)
                if self._is_atomic_block(block):
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
            flush()

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

    def _heading_offsets(self, text: str) -> list[int]:
        """ATX heading starts outside fenced code and HTML tables."""
        cuts: list[int] = []
        offset = 0
        fence: tuple[str, int] | None = None
        table_depth = 0
        for line in text.split("\n"):
            if fence is not None:
                if _is_fence_close(line, fence):
                    fence = None
            elif table_depth > 0:
                table_depth = max(0, table_depth + _html_table_delta(line))
            else:
                opened = _parse_fence_open(line)
                if opened:
                    fence = opened
                else:
                    delta = _html_table_delta(line)
                    if _HTML_TABLE_OPEN.search(line):
                        table_depth = max(0, delta)
                    elif _HEADING.match(line):
                        cuts.append(offset)
            offset += len(line) + 1
        return cuts

    def _split_heading_sections(self, text: str) -> list[str]:
        cuts = self._heading_offsets(text)
        if not cuts:
            return [text]
        sections: list[str] = []
        if cuts[0] > 0:
            prefix = text[: cuts[0]].strip()
            if prefix:
                sections.append(prefix)
        for i, start in enumerate(cuts):
            end = cuts[i + 1] if i + 1 < len(cuts) else len(text)
            section = text[start:end].strip()
            if section:
                sections.append(section)
        return sections

    def _markdown_blocks(self, section: str) -> list[str]:
        blocks: list[str] = []
        buf: list[str] = []
        in_pipe_table = False
        fence: tuple[str, int] | None = None
        table_depth = 0

        def flush_buf() -> None:
            nonlocal buf, in_pipe_table
            joined = "\n".join(buf).strip()
            if joined:
                blocks.append(joined)
            buf = []
            in_pipe_table = False

        for line in section.split("\n"):
            if fence is not None:
                buf.append(line)
                if _is_fence_close(line, fence):
                    fence = None
                    flush_buf()
                continue

            if table_depth > 0:
                buf.append(line)
                table_depth = max(0, table_depth + _html_table_delta(line))
                if table_depth == 0:
                    flush_buf()
                continue

            opened = _parse_fence_open(line)
            if opened:
                if buf:
                    flush_buf()
                fence = opened
                buf.append(line)
                continue

            if _HTML_TABLE_OPEN.search(line):
                if buf:
                    flush_buf()
                buf.append(line)
                table_depth = max(0, _html_table_delta(line))
                if table_depth == 0:
                    flush_buf()
                continue

            is_table_line = bool(_TABLE_LINE.match(line))
            if is_table_line:
                if buf and not in_pipe_table:
                    flush_buf()
                in_pipe_table = True
                buf.append(line)
                continue
            if in_pipe_table:
                flush_buf()
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

    @classmethod
    def _is_atomic_block(cls, block: str) -> bool:
        stripped = block.strip()
        if not stripped:
            return False
        if cls._is_table_block(block):
            return True
        first = stripped.split("\n", 1)[0]
        if _parse_fence_open(first):
            return True
        return _HTML_TABLE_OPEN.search(stripped) is not None

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
