"""Models matching Parser Service OpenAPI (http://…:17000/docs) ParseResponse."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    """Bounding box with coordinate origin."""

    model_config = ConfigDict(populate_by_name=True)

    left: float = Field(default=0.0, alias="l")
    top: float = Field(default=0.0, alias="t")
    right: float = Field(default=0.0, alias="r")
    bottom: float = Field(default=0.0, alias="b")
    coord_origin: str = "TOPLEFT"


class Provenance(BaseModel):
    """Provenance information for a result element."""

    page_no: int
    bbox: BoundingBox | None = None
    charspan: list[Any] = Field(default_factory=list)


class ResultItem(BaseModel):
    """A single document element with its content and provenance."""

    id: str = Field(description="UUID for this element")
    type: str = Field(description="Element type (free-form, backend-dependent)")
    markdown: str = Field(description="Element content in markdown format")
    prov: list[Provenance] = Field(default_factory=list)


class PageInfo(BaseModel):
    """Information about a single page."""

    page_no: int
    size: dict[str, Any] | None = Field(
        default=None, description="Page dimensions {width, height}"
    )
    image: Any | None = Field(default=None, description="Page image metadata (uri stripped)")


class ParseResponse(BaseModel):
    """Synchronous response from document parsing (Parser Service)."""

    status: str = Field(description="SUCCESS or FAIL")
    results: list[ResultItem] = Field(default_factory=list)
    pages: dict[str, PageInfo] = Field(default_factory=dict)
    processing_time_ms: float | None = None
    error: str | None = None
    rendered_document: str | None = Field(
        default=None,
        description="Full document rendered as markdown or HTML (set via output_format)",
    )

    def markdown_text(self) -> str:
        if self.rendered_document and self.rendered_document.strip():
            return self.rendered_document.strip()
        parts = [item.markdown.strip() for item in self.results if item.markdown.strip()]
        if not parts:
            raise ValueError("Parse response has no markdown content")
        return "\n\n".join(parts)
