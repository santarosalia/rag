from __future__ import annotations

from dataclasses import dataclass
from io import StringIO

import tiktoken
from llama_index.core import Document
from llama_index.core.node_parser import (
    HierarchicalNodeParser,
    MarkdownElementNodeParser,
    get_leaf_nodes,
)

_ATOMIC = frozenset({"table", "table_text", "code"})


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    page: int | None = None
    token_count: int = 0
    role: str = "child"
    kind: str = "prose"
    parent_key: str | None = None


class MarkdownChunker:
    """LlamaIndex elements for tables/code, HierarchicalNodeParser for prose.

    ``MarkdownElementNodeParser.extract_elements`` + ``extract_html_tables``
    identify tables and fences. Table summaries (LLM) are not used. Prose and
    titles go through a 2048→768 hierarchy. Search leaves are children; parents
    are consecutive-child windows up to ``parent_max_tokens``.
    """

    def __init__(
        self,
        max_tokens: int = 768,
        parent_max_tokens: int = 2048,
        overlap_tokens: int = 128,
        table_child_max_tokens: int = 256,
        encoding_name: str = "cl100k_base",
    ) -> None:
        self.max_tokens = max_tokens
        self.parent_max_tokens = parent_max_tokens
        self.overlap_tokens = min(overlap_tokens, max(0, max_tokens - 1))
        self.table_child_max_tokens = table_child_max_tokens
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        self._elements = MarkdownElementNodeParser()
        self._hierarchy = HierarchicalNodeParser.from_defaults(
            chunk_sizes=[self.parent_max_tokens, self.max_tokens],
            chunk_overlap=self.overlap_tokens,
        )

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, page: int | None = None) -> list[TextChunk]:
        text = text.strip()
        if not text:
            return []

        parts = self._child_parts(text)
        if not parts:
            return []

        parents: list[TextChunk] = []
        children: list[TextChunk] = []
        for window_idx, window in enumerate(self._parent_windows(parts)):
            parent_key = f"w{window_idx}"
            parent_content = "\n\n".join(content for _, content in window).strip()
            parent_kind = window[0][0] if len(window) == 1 else "prose"
            parents.append(
                TextChunk(
                    content=parent_content,
                    chunk_index=len(parents),
                    page=page,
                    token_count=self.count_tokens(parent_content),
                    role="parent",
                    kind=parent_kind,
                    parent_key=parent_key,
                )
            )
            for kind, content in window:
                children.append(
                    TextChunk(
                        content=content,
                        chunk_index=len(children),
                        page=page,
                        token_count=self.count_tokens(content),
                        role="child",
                        kind=kind,
                        parent_key=parent_key,
                    )
                )
        return [*parents, *children]

    def _child_parts(self, text: str) -> list[tuple[str, str]]:
        elements = self._elements.extract_elements(text)
        elements = self._elements.extract_html_tables(elements)
        parts: list[tuple[str, str]] = []
        prose: list[str] = []

        def flush_prose() -> None:
            body = "\n\n".join(prose).strip()
            prose.clear()
            if not body:
                return
            parts.extend(("prose", leaf) for leaf in self._prose_leaves(body))

        for element in elements:
            kind = element.type
            raw = str(element.element or "").strip()
            if not raw and kind != "code":
                continue
            if kind == "title":
                prose.append(self._format_title(element))
                continue
            if kind == "text":
                prose.append(raw)
                continue
            if kind in _ATOMIC:
                flush_prose()
                if kind == "code":
                    parts.append(("fence", self._format_fence(raw)))
                else:
                    for piece in self._table_children(raw, getattr(element, "table", None)):
                        parts.append(("table", piece))
                continue
            prose.append(raw)

        flush_prose()
        if parts:
            return parts
        return [("prose", leaf) for leaf in self._prose_leaves(text)]

    def _prose_leaves(self, text: str) -> list[str]:
        nodes = self._hierarchy.get_nodes_from_documents([Document(text=text)])
        leaves = [
            node.get_content().strip()
            for node in get_leaf_nodes(nodes)
            if node.get_content().strip()
        ]
        return leaves or [text]

    def _format_title(self, element: object) -> str:
        heading = str(getattr(element, "element", "") or "").strip()
        level = getattr(element, "title_level", None)
        if not isinstance(level, int) or level < 1:
            level = 1
        level = min(level, 6)
        return f"{'#' * level} {heading}".strip()

    @staticmethod
    def _format_fence(body: str) -> str:
        inner = body.strip("\n")
        if inner.startswith("```"):
            return inner if inner.endswith("```") else f"{inner}\n```"
        return f"```\n{inner}\n```"

    def _table_children(self, raw: str, frame: object | None) -> list[str]:
        if self.count_tokens(raw) <= self.max_tokens:
            return [raw]
        parsed = frame if frame is not None else self._html_frame(raw)
        if parsed is None:
            return [raw]
        try:
            row_count = len(parsed)
        except TypeError:
            return [raw]
        if row_count <= 1:
            return [raw]
        return self._split_frame(parsed)

    def _html_frame(self, raw: str):
        if "<table" not in raw.lower():
            return None
        try:
            import pandas as pd
        except ImportError:
            return None
        try:
            frames = pd.read_html(StringIO(raw))
        except (ValueError, ImportError):
            return None
        return frames[0] if frames else None

    def _split_frame(self, frame: object) -> list[str]:
        n = len(frame)
        pieces: list[str] = []
        start = 0
        while start < n:
            end = start + 1
            piece = self._frame_to_pipe(frame.iloc[start:end])
            while end < n:
                candidate = self._frame_to_pipe(frame.iloc[start : end + 1])
                if (
                    self.count_tokens(candidate) > self.table_child_max_tokens
                    and end > start
                ):
                    break
                end += 1
                piece = candidate
            pieces.append(piece)
            start = end
        return pieces or [self._frame_to_pipe(frame)]

    @staticmethod
    def _frame_to_pipe(frame: object) -> str:
        columns = [str(col) for col in list(frame.columns)]
        header = "| " + " | ".join(columns) + " |"
        divider = "| " + " | ".join("---" for _ in columns) + " |"
        rows = []
        for row in frame.itertuples(index=False, name=None):
            cells = ["" if cell is None else str(cell) for cell in row]
            rows.append("| " + " | ".join(cells) + " |")
        return "\n".join([header, divider, *rows])

    def _parent_windows(self, parts: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        windows: list[list[tuple[str, str]]] = []
        current: list[tuple[str, str]] = []
        current_tokens = 0
        for part in parts:
            tokens = self.count_tokens(part[1])
            if current and current_tokens + tokens > self.parent_max_tokens:
                windows.append(current)
                current = [part]
                current_tokens = tokens
            else:
                current.append(part)
                current_tokens += tokens
        if current:
            windows.append(current)
        return windows
