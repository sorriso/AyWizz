# =============================================================================
# File: models.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c7_memory/models.py
# Description: Pydantic v2 models for the C7 Memory Service. Mirrors the
#              contract-critical entities E-400-001..005 from
#              400-SPEC-MEMORY-RAG.
#
# @relation implements:R-400-010
# @relation implements:R-400-040
# @relation implements:E-400-002
# @relation implements:E-400-003
# =============================================================================

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class IndexKind(StrEnum):
    """Two logical indexes per R-400-010 / D-013."""

    REQUIREMENTS = "requirements"
    EXTERNAL_SOURCES = "external_sources"


class ChunkStatus(StrEnum):
    """Status of an embedded chunk — used for retrieval filtering."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"


class ParseStatus(StrEnum):
    """Ingestion pipeline status on a source (R-400-020)."""

    PENDING = "pending"
    PARSED = "parsed"
    INDEXED = "indexed"
    FAILED = "failed"


class RefreshJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Public chunk / source views (wire-level)
# ---------------------------------------------------------------------------


class ChunkPublic(BaseModel):
    """A single retrievable chunk — returned by the retriever."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    project_id: str
    index: IndexKind
    source_id: str | None = None
    entity_id: str | None = None
    entity_version: int | None = None
    chunk_index: int
    content: str
    content_hash: str
    model_id: str
    model_dim: int
    created_at: datetime
    status: ChunkStatus
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourcePublic(BaseModel):
    """Metadata about an uploaded external source (E-400-003)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    project_id: str
    mime_type: str
    size_bytes: int
    uploaded_by: str
    uploaded_at: datetime
    parse_status: ParseStatus
    parse_error: str | None = None
    chunk_count: int
    model_id: str | None = None


# ---------------------------------------------------------------------------
# Retrieval surface (R-400-040)
# ---------------------------------------------------------------------------


class RetrievalRequest(BaseModel):
    """POST /api/v1/memory/retrieve body."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    query: str = Field(min_length=1)
    indexes: list[IndexKind] = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    weights: dict[IndexKind, float] | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    include_history: bool = False
    include_deprecated: bool = False


class RetrievalHit(BaseModel):
    """One hit in a retrieval response (includes score + provenance)."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    index: IndexKind
    score: float
    content: str
    snippet: str
    source_id: str | None = None
    entity_id: str | None = None
    entity_version: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    """Federated retrieval response (R-400-040)."""

    model_config = ConfigDict(extra="forbid")

    retrieval_id: str
    request: RetrievalRequest
    hits: list[RetrievalHit] = Field(default_factory=list)
    latency_ms: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Ingestion entry point (v1 has C7 receive *parsed* payloads — uploads live
# on C12, see R-400-020). This model is used both for NATS payloads and for
# the admin-only direct-ingest endpoint used by tests and operators.
# ---------------------------------------------------------------------------


class SourceIngestRequest(BaseModel):
    """Direct ingestion of an already-parsed source (admin/test surface)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    project_id: str
    mime_type: Literal["text/plain", "text/markdown", "application/pdf", "image/png", "image/jpeg"]
    content: str = Field(min_length=1)
    size_bytes: int = Field(ge=1)
    uploaded_by: str


class EntityEmbedRequest(BaseModel):
    """Event-driven request to (re)embed a C5 entity (R-400-030)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    entity_id: str
    entity_version: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    # When true, prior versions of this entity remain as `superseded` in the
    # index (R-400-031). When false, they are deleted.
    preserve_history: bool = True


# ---------------------------------------------------------------------------
# Refresh jobs (R-400-061)
# ---------------------------------------------------------------------------


class RefreshJob(BaseModel):
    """Admin refresh job descriptor."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str
    status: RefreshJobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    processed_chunks: int = 0
    total_chunks: int | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


class QuotaStatus(BaseModel):
    """GET /api/v1/memory/projects/{pid}/quota response (R-400-024)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    bytes_used: int
    bytes_limit: int
    chunk_count: int
    source_count: int


# ---------------------------------------------------------------------------
# List envelopes
# ---------------------------------------------------------------------------


class SourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourcePublic]


class ChunkListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[ChunkPublic]
