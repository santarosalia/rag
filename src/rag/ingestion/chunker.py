from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import tiktoken
from llama_index.core.node_parser import MarkdownElementNodeParser

_HEADING = re.compile(r"(?m)^#{1,6}\s+")
_TABLE_ELEMENT_TYPES = frozenset({"table", "table_text"})
_ATOMIC_ELEMENT_TYPES = frozenset({"table", "table_text", "code"})


class BlockKind(StrEnum):
    HEADING = "heading"
    PROSE = "prose"
    ATOMIC = "atomic"


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0


@dataclass(frozen=True)
class _Block:
    kind: BlockKind
    text: str


class MarkdownChunker:
    """Markdown → Element boundaries → ChunkBag → TextChunk list.

    LlamaIndex detects title/text/table/code. Assembly uses a token bag
    (max_tokens, overlap, min_chunk_tokens). Small tables join the bag as
    prose; large tables/code stay atomic. Short trailing chunks are merged
    into the previous chunk by size only (no domain keyword lists).
    """

    def __init__(
        self,
        max_tokens: int = 768,
        overlap_tokens: int = 128,
        min_chunk_tokens: int = 64,
        small_table_max_tokens: int = 128,
        small_table_max_rows: int = 8,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.small_table_max_tokens = small_table_max_tokens
        self.small_table_max_rows = small_table_max_rows
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

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, page: int | None = None) -> list[TextChunk]:
        text = text.strip()
        if not text:
            return []

        blocks = self._elements_to_blocks(text)
        chunks = self._assemble_bag(blocks, page)
        return self._merge_short_trailing(chunks, page)

    def _elements_to_blocks(self, text: str) -> list[_Block]:
        elements = self._element_parser.extract_elements(
            text,
            table_filters=[self._element_parser.filter_table],
        )
        elements = self._element_parser.extract_html_tables(elements)

        blocks: list[_Block] = []
        for element in elements:
            if element.type == "title":
                level = getattr(element, "title_level", None) or 1
                level = max(1, min(int(level), 6))
                heading = f"{'#' * level} {str(element.element).strip()}".strip()
                if heading:
                    blocks.append(_Block(BlockKind.HEADING, heading))
                continue

            body = str(element.element).strip()
            if not body:
                continue

            if element.type in _ATOMIC_ELEMENT_TYPES:
                content = body
                if element.type == "code" and not body.lstrip().startswith("```"):
                    content = f"```\n{body}\n```"
                if element.type in _TABLE_ELEMENT_TYPES and self._is_small_table(content):
                    blocks.append(_Block(BlockKind.PROSE, content))
                else:
                    blocks.append(_Block(BlockKind.ATOMIC, content))
                continue

            blocks.append(_Block(BlockKind.PROSE, body))

        return blocks

    def _is_small_table(self, content: str) -> bool:
        if self.count_tokens(content) > self.small_table_max_tokens:
            return False

        pipe_rows = [line for line in content.splitlines() if "|" in line and line.strip()]
        if pipe_rows:
            return len(pipe_rows) <= self.small_table_max_rows

        tr_count = len(re.findall(r"<tr\b", content, flags=re.IGNORECASE))
        if tr_count:
            return tr_count <= self.small_table_max_rows

        return True

    def _assemble_bag(self, blocks: list[_Block], page: int | None) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        current_parts: list[str] = []
        current_tokens = 0
        chunk_index = 0

        def flush(*, use_overlap: bool = True) -> list[str]:
            nonlocal current_parts, current_tokens, chunk_index
            if not current_parts:
                return []
            content = "\n\n".join(current_parts).strip()
            overlap = self._get_overlap(current_parts) if use_overlap else []
            if not content:
                current_parts = []
                current_tokens = 0
                return overlap

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
            return overlap

        for block in blocks:
            block_tokens = self.count_tokens(block.text)

            if block.kind == BlockKind.ATOMIC:
                if current_tokens + block_tokens > self.max_tokens and current_parts:
                    flush(use_overlap=False)
                current_parts.append(block.text)
                current_tokens = self._parts_tokens(current_parts)
                if current_tokens > self.max_tokens and len(current_parts) == 1:
                    flush(use_overlap=False)
                continue

            if block_tokens > self.max_tokens:
                if current_parts:
                    overlap = flush(use_overlap=True)
                    current_parts = list(overlap)
                    current_tokens = self._parts_tokens(current_parts)
                for sub in self._split_oversized(block.text):
                    sub_tokens = self.count_tokens(sub)
                    if current_tokens + sub_tokens > self.max_tokens and current_parts:
                        overlap = flush(use_overlap=True)
                        current_parts = list(overlap)
                        current_tokens = self._parts_tokens(current_parts)
                    if sub_tokens > self.max_tokens:
                        if current_parts:
                            flush(use_overlap=False)
                        chunks.append(self._make_chunk(sub, chunk_index, page))
                        chunk_index += 1
                        continue
                    current_parts.append(sub)
                    current_tokens = self._parts_tokens(current_parts)
                continue

            if current_tokens + block_tokens > self.max_tokens and current_parts:
                overlap = flush(use_overlap=True)
                current_parts = list(overlap)
                current_tokens = self._parts_tokens(current_parts)

            current_parts.append(block.text)
            current_tokens = self._parts_tokens(current_parts)

        if current_parts:
            flush(use_overlap=False)

        return chunks

    def _merge_short_trailing(self, chunks: list[TextChunk], page: int | None) -> list[TextChunk]:
        """Append short last chunks to the previous one (size-only)."""
        if len(chunks) < 2:
            return chunks

        merged = list(chunks)
        while len(merged) >= 2:
            last = merged[-1]
            if last.token_count >= self.min_chunk_tokens:
                break
            if _HEADING.match(last.content):
                break
            prev = merged[-2]
            combined = self._make_chunk(
                f"{prev.content}\n\n{last.content}",
                prev.chunk_index,
                page,
            )
            merged = [*merged[:-2], combined]

        for i, chunk in enumerate(merged):
            chunk.chunk_index = i
        return merged

    def _parts_tokens(self, parts: list[str]) -> int:
        if not parts:
            return 0
        return self.count_tokens("\n\n".join(parts))

    def _make_chunk(self, content: str, chunk_index: int, page: int | None) -> TextChunk:
        stripped = content.strip()
        return TextChunk(
            content=stripped,
            chunk_index=chunk_index,
            page=page,
            token_count=self.count_tokens(stripped),
        )

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
