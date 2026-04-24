# =============================================================================
# File: service.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c7_memory/service.py
# Description: Facade for the C7 Memory Service. Wires ingestion (parse +
#              chunk + embed + index), federated retrieval, entity-event
#              handlers, and the admin surface.
#
# @relation implements:R-400-020
# @relation implements:R-400-030
# @relation implements:R-400-031
# @relation implements:R-400-040
# @relation implements:R-400-042
# @relation implements:R-400-070
# @relation implements:R-400-071
# =============================================================================

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.base import EmbeddingProvider
from ay_platform_core.c7_memory.ingestion.chunker import chunk_text
from ay_platform_core.c7_memory.ingestion.parser import UnsupportedMimeError, parse
from ay_platform_core.c7_memory.models import (
    ChunkPublic,
    ChunkStatus,
    EntityEmbedRequest,
    IndexKind,
    ParseStatus,
    QuotaStatus,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResponse,
    SourceIngestRequest,
    SourceListResponse,
    SourcePublic,
)
from ay_platform_core.c7_memory.retrieval.similarity import cosine, snippet


class MemoryService:
    """Public API of the Memory Service."""

    def __init__(
        self,
        config: MemoryConfig,
        repo: MemoryRepository,
        embedder: EmbeddingProvider,
    ) -> None:
        self._config = config
        self._repo = repo
        self._embedder = embedder

    # ------------------------------------------------------------------
    # Ingestion (admin/test direct path — C12 upload still goes via NATS
    # in production; this lets operators and integration tests ingest
    # pre-parsed content without spinning up the full pipeline)
    # ------------------------------------------------------------------

    async def ingest_source(
        self, payload: SourceIngestRequest, *, tenant_id: str
    ) -> SourcePublic:
        await self._enforce_quota(tenant_id, payload.project_id, payload.size_bytes)

        try:
            text = parse(payload.mime_type, payload.content.encode("utf-8"))
        except UnsupportedMimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            ) from exc
        except NotImplementedError as exc:
            # PDF/image parsers not wired — return 501 with a clear message.
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
            ) from exc

        chunks = chunk_text(
            text,
            token_size=self._config.chunk_token_size,
            overlap=self._config.chunk_overlap,
        )
        if not chunks:
            # Empty source is a legitimate but boring case — record it so
            # the operator sees why retrieval returns nothing.
            source_row = _source_row(
                payload=payload,
                tenant_id=tenant_id,
                model_id=self._embedder.model_id,
                chunk_count=0,
                parse_status=ParseStatus.PARSED,
            )
            await self._repo.upsert_source(source_row)
            return _source_public(source_row)

        vectors = await self._embedder.embed_batch([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError(
                "embedder returned a different number of vectors than "
                "input chunks — adapter contract violation"
            )
        if any(len(v) != self._embedder.dimension for v in vectors):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "embedder produced a vector of unexpected dimension; "
                    "declared dim does not match actual output"
                ),
            )

        now = datetime.now(UTC).isoformat()
        chunk_rows: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            content_hash = "sha256:" + hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            chunk_id = f"{payload.source_id}:{chunk.index}"
            chunk_rows.append({
                "_key": f"{tenant_id}:{payload.project_id}:{chunk_id}",
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "project_id": payload.project_id,
                "index": IndexKind.EXTERNAL_SOURCES.value,
                "source_id": payload.source_id,
                "entity_id": None,
                "entity_version": None,
                "chunk_index": chunk.index,
                "content": chunk.text,
                "content_hash": content_hash,
                "vector": vector,
                "model_id": self._embedder.model_id,
                "model_dim": self._embedder.dimension,
                "created_at": now,
                "status": ChunkStatus.ACTIVE.value,
                "metadata": {"mime_type": payload.mime_type},
            })
        await self._repo.upsert_chunks(chunk_rows)
        source_row = _source_row(
            payload=payload,
            tenant_id=tenant_id,
            model_id=self._embedder.model_id,
            chunk_count=len(chunks),
            parse_status=ParseStatus.INDEXED,
        )
        await self._repo.upsert_source(source_row)
        return _source_public(source_row)

    async def delete_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> None:
        existing = await self._repo.get_source(tenant_id, project_id, source_id)
        if existing is None:
            # R-400-071: 404, not 403 — do not leak tenant boundaries.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
            )
        await self._repo.delete_chunks_for_source(tenant_id, project_id, source_id)
        await self._repo.delete_source(tenant_id, project_id, source_id)

    async def list_sources(
        self, tenant_id: str, project_id: str
    ) -> SourceListResponse:
        rows = await self._repo.list_sources(tenant_id, project_id)
        return SourceListResponse(sources=[_source_public(r) for r in rows])

    async def get_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> SourcePublic:
        row = await self._repo.get_source(tenant_id, project_id, source_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
            )
        return _source_public(row)

    # ------------------------------------------------------------------
    # Entity embedding (R-400-030) — triggered by requirements events.
    # Exposed as a method so C5 event consumers (or tests) can call it
    # directly; in production an async worker would dequeue from NATS
    # and invoke this path.
    # ------------------------------------------------------------------

    async def embed_entity(
        self, payload: EntityEmbedRequest, *, tenant_id: str
    ) -> ChunkPublic:
        vector = await self._embedder.embed_one(payload.content)
        if len(vector) != self._embedder.dimension:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="embedder produced vector of unexpected dimension",
            )

        if payload.preserve_history:
            await self._repo.mark_entity_superseded(
                tenant_id, payload.project_id, payload.entity_id, payload.entity_version
            )

        now = datetime.now(UTC).isoformat()
        content_hash = "sha256:" + hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
        chunk_id = f"{payload.entity_id}@v{payload.entity_version}"
        row: dict[str, Any] = {
            "_key": f"{tenant_id}:{payload.project_id}:{chunk_id}",
            "chunk_id": chunk_id,
            "tenant_id": tenant_id,
            "project_id": payload.project_id,
            "index": IndexKind.REQUIREMENTS.value,
            "source_id": None,
            "entity_id": payload.entity_id,
            "entity_version": payload.entity_version,
            "chunk_index": 0,
            "content": payload.content,
            "content_hash": content_hash,
            "vector": vector,
            "model_id": self._embedder.model_id,
            "model_dim": self._embedder.dimension,
            "created_at": now,
            "status": ChunkStatus.ACTIVE.value,
            "metadata": dict(payload.metadata),
        }
        await self._repo.upsert_chunk(row)
        return _chunk_public(row)

    # ------------------------------------------------------------------
    # Retrieval (R-400-040)
    # ------------------------------------------------------------------

    async def retrieve(
        self, payload: RetrievalRequest, *, tenant_id: str
    ) -> RetrievalResponse:
        started = time.monotonic()
        # R-400-042: the query is embedded with the ACTIVE embedder; we
        # only compare against stored chunks that used the same model.
        query_vector = await self._embedder.embed_one(payload.query)

        rows = await self._repo.scan_chunks(
            tenant_id=tenant_id,
            project_id=payload.project_id,
            indexes=[ix.value for ix in payload.indexes],
            model_id=self._embedder.model_id,
            include_deprecated=payload.include_deprecated,
            include_history=payload.include_history,
            scan_cap=self._config.retrieval_scan_cap,
        )
        # Apply post-scan filters (metadata + history) — kept Python-side
        # so the AQL scan stays simple and the repository remains reusable.
        filtered = [
            r for r in rows if _row_matches_filters(r, payload)
        ]

        weights = payload.weights or {}

        def _weighted_score(row: dict[str, Any]) -> float:
            raw = cosine(query_vector, list(row["vector"]))
            multiplier = weights.get(IndexKind(row["index"]), 1.0)
            return raw * multiplier

        scored = [(row, _weighted_score(row)) for row in filtered]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        top = scored[: payload.top_k]

        hits = [
            RetrievalHit(
                chunk_id=row["chunk_id"],
                index=IndexKind(row["index"]),
                score=score,
                content=row["content"],
                snippet=snippet(row["content"]),
                source_id=row.get("source_id"),
                entity_id=row.get("entity_id"),
                entity_version=row.get("entity_version"),
                metadata=dict(row.get("metadata", {})),
            )
            for row, score in top
        ]
        return RetrievalResponse(
            retrieval_id=str(uuid.uuid4()),
            request=payload,
            hits=hits,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    # ------------------------------------------------------------------
    # Quota (R-400-024)
    # ------------------------------------------------------------------

    async def quota(self, tenant_id: str, project_id: str) -> QuotaStatus:
        totals = await self._repo.quota_totals(tenant_id, project_id)
        return QuotaStatus(
            project_id=project_id,
            bytes_used=totals["bytes_used"],
            bytes_limit=self._config.default_quota_bytes,
            chunk_count=totals["chunk_count"],
            source_count=totals["source_count"],
        )

    async def _enforce_quota(
        self, tenant_id: str, project_id: str, incoming_bytes: int
    ) -> None:
        totals = await self._repo.quota_totals(tenant_id, project_id)
        if totals["bytes_used"] + incoming_bytes > self._config.default_quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"project quota exceeded: {totals['bytes_used']} + "
                    f"{incoming_bytes} > {self._config.default_quota_bytes}"
                ),
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _source_row(
    *,
    payload: SourceIngestRequest,
    tenant_id: str,
    model_id: str,
    chunk_count: int,
    parse_status: ParseStatus,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "_key": f"{tenant_id}:{payload.project_id}:{payload.source_id}",
        "tenant_id": tenant_id,
        "project_id": payload.project_id,
        "source_id": payload.source_id,
        "minio_raw_path": None,
        "minio_parsed_path": None,
        "minio_chunks_path": None,
        "mime_type": payload.mime_type,
        "size_bytes": payload.size_bytes,
        "uploaded_by": payload.uploaded_by,
        "uploaded_at": now,
        "parse_status": parse_status.value,
        "parse_error": None,
        "chunk_count": chunk_count,
        "model_id": model_id,
    }


def _source_public(row: dict[str, Any]) -> SourcePublic:
    return SourcePublic(
        source_id=row["source_id"],
        project_id=row["project_id"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        uploaded_by=row["uploaded_by"],
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
        parse_status=ParseStatus(row["parse_status"]),
        parse_error=row.get("parse_error"),
        chunk_count=row.get("chunk_count", 0),
        model_id=row.get("model_id"),
    )


def _chunk_public(row: dict[str, Any]) -> ChunkPublic:
    return ChunkPublic(
        chunk_id=row["chunk_id"],
        project_id=row["project_id"],
        index=IndexKind(row["index"]),
        source_id=row.get("source_id"),
        entity_id=row.get("entity_id"),
        entity_version=row.get("entity_version"),
        chunk_index=row["chunk_index"],
        content=row["content"],
        content_hash=row["content_hash"],
        model_id=row["model_id"],
        model_dim=row["model_dim"],
        created_at=datetime.fromisoformat(row["created_at"]),
        status=ChunkStatus(row["status"]),
        metadata=dict(row.get("metadata", {})),
    )


def _row_matches_filters(row: dict[str, Any], payload: RetrievalRequest) -> bool:
    """Post-scan filtering: metadata + history gating.

    - `include_history=False` (default): for each entity_id, only the
      latest active version. Deprecated chunks are governed by
      `include_deprecated`.
    - `filters`: simple key/value match against row['metadata'] and
      top-level fields.
    """
    # History: when False, drop superseded requirement-entity chunks.
    if (
        not payload.include_history
        and row.get("entity_id") is not None
        and row.get("status") == ChunkStatus.SUPERSEDED.value
    ):
        return False
    # Metadata filter: every declared key SHALL match.
    for key, expected in payload.filters.items():
        actual = row.get(key)
        if actual is None:
            actual = row.get("metadata", {}).get(key)
        if actual != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_service(request: Request) -> MemoryService:
    svc = getattr(request.app.state, "memory_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory service not initialised",
        )
    return svc  # type: ignore[no-any-return]
