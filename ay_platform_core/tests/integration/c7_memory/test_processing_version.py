# =============================================================================
# File: test_processing_version.py
# Version: 1
# Path: ay_platform_core/tests/integration/c7_memory/test_processing_version.py
# Description: Integration test for R-400-208 — a source is stamped with its
#              processing_version, GET surfaces is_stale when the pipeline
#              version changes, and POST .../reprocess re-runs the pipeline
#              and re-stamps the current version. Also: reprocess on a
#              string-ingested source (no raw bytes) returns 409.
#
# @relation validates:R-400-208
# =============================================================================

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.deterministic import DeterministicHashEmbedder
from ay_platform_core.c7_memory.models import SourceIngestRequest
from ay_platform_core.c7_memory.service import MemoryService
from ay_platform_core.c7_memory.storage.minio_storage import MemorySourceStorage

_TENANT = "t-pv"
_PROJECT = "p-pv"
_TEXT = (
    "Marie Curie discovered polonium and radium while working in Paris. "
    "She taught at the Sorbonne and won two Nobel prizes, one in physics "
    "and one in chemistry, for her pioneering research on radioactivity "
    "over the course of many demanding years in the laboratory."
)


def _service(
    repo: MemoryRepository,
    storage: MemorySourceStorage,
    embedder: DeterministicHashEmbedder,
    *,
    chunk_size: int,
    overlap: int,
) -> MemoryService:
    return MemoryService(
        config=MemoryConfig(
            embedding_adapter="deterministic-hash",
            embedding_model_id="deterministic-hash-v1",
            embedding_dimension=embedder.dimension,
            chunk_token_size=chunk_size,
            chunk_overlap=overlap,
            default_quota_bytes=1024 * 1024 * 1024,
            retrieval_scan_cap=1000,
        ),
        repo=repo,
        embedder=embedder,
        storage=storage,
    )


async def test_stamp_then_stale_then_reprocess(
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
    c7_deterministic_embedder: DeterministicHashEmbedder,
) -> None:
    # Ingest with pipeline v1 (chunk 64/8). Freshly ingested -> not stale.
    svc_v1 = _service(c7_repo, c7_storage, c7_deterministic_embedder, chunk_size=64, overlap=8)
    pub = await svc_v1.ingest_uploaded_source(
        tenant_id=_TENANT,
        project_id=_PROJECT,
        source_id="src-pv-1",
        mime_type="text/plain",
        uploaded_by="u1",
        content_bytes=_TEXT.encode("utf-8"),
    )
    assert pub.is_stale is False
    assert pub.processing_version == "chunk=64/8;embed=deterministic-hash-v1"

    # A service with a CHANGED chunk config = a new pipeline version. The
    # stored source is now stale w.r.t. this pipeline.
    svc_v2 = _service(c7_repo, c7_storage, c7_deterministic_embedder, chunk_size=32, overlap=4)
    stale = await svc_v2.get_source(_TENANT, _PROJECT, "src-pv-1")
    assert stale.processing_version == "chunk=64/8;embed=deterministic-hash-v1"
    assert stale.is_stale is True

    # Reprocess from the persisted raw bytes -> re-stamp the current version.
    re = await svc_v2.reprocess_source(
        tenant_id=_TENANT, project_id=_PROJECT, source_id="src-pv-1",
    )
    assert re.processing_version == "chunk=32/4;embed=deterministic-hash-v1"
    assert re.is_stale is False

    after = await svc_v2.get_source(_TENANT, _PROJECT, "src-pv-1")
    assert after.is_stale is False
    assert after.processing_version == "chunk=32/4;embed=deterministic-hash-v1"


async def test_reprocess_409_when_no_raw_bytes(
    c7_repo: MemoryRepository,
    c7_storage: MemorySourceStorage,
    c7_deterministic_embedder: DeterministicHashEmbedder,
) -> None:
    """A source ingested via the JSON `POST /sources` path has no raw blob,
    so it cannot be reprocessed -> 409 (R-400-208)."""
    svc = _service(c7_repo, c7_storage, c7_deterministic_embedder, chunk_size=64, overlap=8)
    await svc.ingest_source(
        SourceIngestRequest(
            source_id="src-pv-nostorage",
            project_id=_PROJECT,
            mime_type="text/plain",
            content=_TEXT,
            size_bytes=len(_TEXT),
            uploaded_by="u1",
        ),
        tenant_id=_TENANT,
    )
    with pytest.raises(HTTPException) as exc:
        await svc.reprocess_source(
            tenant_id=_TENANT, project_id=_PROJECT, source_id="src-pv-nostorage",
        )
    assert exc.value.status_code == 409


async def test_reprocess_route_http_409_for_string_source(
    c7_upload_app: FastAPI,
) -> None:
    """HTTP-level smoke for `POST .../sources/{id}/reprocess` (R-400-208):
    a JSON-ingested source has no raw bytes, so reprocess returns 409
    through the router (verifies wiring + auth + behaviour)."""
    headers = {
        "X-User-Id": "u1",
        "X-Tenant-Id": "t-http",
        "X-User-Roles": "project_editor,project_owner,admin",
    }
    transport = httpx.ASGITransport(app=c7_upload_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/memory/projects/p-http/sources",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "source_id": "s-http",
                "project_id": "p-http",
                "mime_type": "text/plain",
                "content": _TEXT,
                "size_bytes": len(_TEXT),
                "uploaded_by": "u1",
            },
        )
        assert created.status_code in (200, 201), created.text

        reprocessed = await client.post(
            "/api/v1/memory/projects/p-http/sources/s-http/reprocess",
            headers=headers,
        )
        assert reprocessed.status_code == 409, reprocessed.text
