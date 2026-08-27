from io import BytesIO
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError:  # pragma: no cover
    MarkItDown = None  # type: ignore[misc, assignment]


def to_markdown(data: bytes, *, filename: str, already_markdown: bool) -> str:
    if already_markdown:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            raise ValueError("No content extracted from document")
        return text

    if MarkItDown is None:
        raise RuntimeError("markitdown is not installed")

    converter = MarkItDown()
    extension = Path(filename).suffix or None
    result = converter.convert_stream(BytesIO(data), file_extension=extension)
    text = (getattr(result, "markdown", None) or getattr(result, "text_content", "") or "").strip()
    if not text:
        raise ValueError("No content extracted from document")
    return text
