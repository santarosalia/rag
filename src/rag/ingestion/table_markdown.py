"""HTML table → Markdown (DocuOps `table_markdown` 이식).

임베딩·행 분할 전에 HTML/CSS 노이즈를 제거하고 rowspan/colspan을 격자로 전개한다.
원본: docuops_ml_api/services/common/table_markdown.py
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _RowParser(HTMLParser):
    """Depth-aware HTML table row parser (rowspan/colspan, skips nested tables)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple]] = []
        self._cur: list[tuple] = []
        self._buf: str = ""
        self._in_cell: bool = False
        self._rspan: int = 1
        self._cspan: int = 1
        self._table_depth: int = 0
        self._in_thead: bool = False
        self.header_count: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth > 1 and self._in_cell:
                self._buf += " "
            return
        if self._table_depth > 1:
            return
        if tag == "thead":
            self._in_thead = True
            return
        if tag in ("td", "th"):
            self._in_cell = True
            self._buf = ""
            a = dict(attrs)
            try:
                self._rspan = int(a.get("rowspan") or 1)
            except ValueError:
                self._rspan = 1
            try:
                self._cspan = int(a.get("colspan") or 1)
            except ValueError:
                self._cspan = 1
        elif tag == "tr":
            self._cur = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._table_depth > 0:
                self._table_depth -= 1
            return
        if self._table_depth > 1:
            return
        if tag == "thead":
            self._in_thead = False
            return
        if tag in ("td", "th"):
            if not self._in_cell:
                return
            self._in_cell = False
            self._cur.append((self._buf.strip(), self._rspan, self._cspan))
            self._rspan = self._cspan = 1
        elif tag == "tr":
            if self._cur:
                self.rows.append(self._cur)
                if self._in_thead:
                    self.header_count += 1

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf += data

    def handle_entityref(self, name: str) -> None:
        if self._in_cell:
            self._buf += f"&{name};"

    def handle_charref(self, name: str) -> None:
        if self._in_cell:
            self._buf += f"&#{name};"


def html_table_to_markdown(html_str: str) -> str:
    """Convert an HTML table to a GitHub-flavored markdown pipe table."""
    rp = _RowParser()
    rp.feed(html_str)
    parsed_rows = rp.rows
    if not parsed_rows:
        return html_str

    n_cols = max(sum(cs for _, _, cs in row) for row in parsed_rows)
    n_rows = len(parsed_rows)
    grid: list[list[str | None]] = [[None] * n_cols for _ in range(n_rows)]

    for r_idx, row_cells in enumerate(parsed_rows):
        c_idx = 0
        for text, rspan, cspan in row_cells:
            while c_idx < n_cols and grid[r_idx][c_idx] is not None:
                c_idx += 1
            if c_idx >= n_cols:
                break
            for dr in range(rspan):
                for dc in range(cspan):
                    tr, tc = r_idx + dr, c_idx + dc
                    if tr < n_rows and tc < n_cols:
                        grid[tr][tc] = text
            c_idx += cspan

    def esc_cell(s: str | None) -> str:
        s = s or ""
        return s.replace("|", "\\|").replace("\n", " ")

    def fmt_row(row: list[str | None]) -> str:
        return "| " + " | ".join(esc_cell(c) for c in row) + " |"

    sep = "| " + " | ".join(["---"] * n_cols) + " |"
    header_n = max(1, min(rp.header_count, n_rows)) if rp.header_count else 1
    lines = [fmt_row(grid[r]) for r in range(header_n)]
    lines.append(sep)
    for row in grid[header_n:]:
        lines.append(fmt_row(row))
    return "\n".join(lines)


def prepare_table_content(content: str) -> str:
    """HTML 표면 Markdown으로 변환; 그 외(파이프 MD 등)는 그대로."""
    if not (content or "").strip():
        return content
    if re.search(r"<t[rdh]", content, re.IGNORECASE):
        return html_table_to_markdown(content)
    return content
