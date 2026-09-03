from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, model_serializer

from rag.groups.ids import GROUP_ID_MAX_LENGTH, GROUP_ID_PATTERN_STR
from rag.models.parse import ParseResponse

GroupId = Annotated[
    str,
    Field(min_length=1, max_length=GROUP_ID_MAX_LENGTH, pattern=GROUP_ID_PATTERN_STR),
]


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    SPARSE = "sparse"


class DocumentUploadResponse(BaseModel):
    doc_id: UUID
    job_id: UUID
    status: DocumentStatus
    message: str = "Document queued for ingestion"
    parse: ParseResponse | None = None


class DocumentResponse(BaseModel):
    doc_id: UUID
    filename: str
    content_type: str
    status: DocumentStatus
    chunk_count: int
    group_id: GroupId
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    mode: SearchMode = SearchMode.HYBRID
    group_id: GroupId | None = None
    top_k: int | None = Field(default=None, ge=1, le=100)
    rerank: bool = True
    snippet: bool = True
    content: bool = False


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    filename: str
    page: int | None
    score: float
    snippet: str | None = None
    rank: int
    content: str | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_bodies(self, serializer):
        data = serializer(self)
        if data.get("snippet") is None:
            data.pop("snippet", None)
        if data.get("content") is None:
            data.pop("content", None)
        return data


def project_citation_bodies(
    citations: list[Citation],
    *,
    snippet: bool,
    content: bool,
) -> list[Citation]:
    return [
        citation.model_copy(
            update={
                "snippet": citation.snippet if snippet else None,
                "content": citation.content if content else None,
            }
        )
        for citation in citations
    ]


class RetrieveResponse(BaseModel):
    query: str
    mode: SearchMode
    backend: str
    citations: list[Citation]
    latency_ms: dict[str, float]


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    group_id: GroupId | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_citations: bool = True
    snippet: bool = True
    content: bool = False


class QueryResponse(BaseModel):
    query: str
    answer: str
    backend: str
    citations: list[Citation]
    latency_ms: dict[str, float]


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, Any]


class GroupCreate(BaseModel):
    id: GroupId | None = None


class GroupResponse(BaseModel):
    id: str
    slug: str | None = None
    created_at: datetime
    updated_at: datetime


class GroupDocumentItem(BaseModel):
    doc_id: UUID
    filename: str
    status: DocumentStatus
    chunk_count: int
    created_at: datetime
