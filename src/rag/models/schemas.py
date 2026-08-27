from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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


class DocumentResponse(BaseModel):
    doc_id: UUID
    filename: str
    content_type: str
    status: DocumentStatus
    chunk_count: int
    group_id: UUID
    group_path: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    mode: SearchMode = SearchMode.HYBRID
    group_id: UUID | None = None
    include_descendants: bool = False
    top_k: int | None = Field(default=None, ge=1, le=100)
    rerank: bool = True


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    filename: str
    page: int | None
    score: float
    snippet: str
    rank: int


class RetrieveResponse(BaseModel):
    query: str
    mode: SearchMode
    backend: str
    citations: list[Citation]
    latency_ms: dict[str, float]


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    group_id: UUID | None = None
    include_descendants: bool = False
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_citations: bool = True


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
    name: str = Field(..., min_length=1, max_length=256)
    parent_id: UUID | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    parent_id: UUID | None = None


class GroupResponse(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    slug: str | None = None
    path: str
    depth: int
    created_at: datetime
    updated_at: datetime


class GroupDetailResponse(GroupResponse):
    children: list[GroupResponse] = Field(default_factory=list)


class GroupTreeNode(GroupResponse):
    children: list["GroupTreeNode"] = Field(default_factory=list)


GroupTreeNode.model_rebuild()


class GroupDocumentItem(BaseModel):
    doc_id: UUID
    filename: str
    status: DocumentStatus
    chunk_count: int
    created_at: datetime
