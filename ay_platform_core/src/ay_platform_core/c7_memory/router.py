# =============================================================================
# File: router.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c7_memory/router.py
# Description: FastAPI APIRouter for C7 per 400-SPEC §6.1. Identity comes
#              from Traefik forward-auth headers (X-User-Id, X-User-Roles,
#              X-Tenant-Id), propagated by C1 / C2 as on the other
#              components.
#
# @relation implements:R-400-040
# @relation implements:R-400-070
# @relation implements:E-400-005
# C7 also realises the C7 side of the C12 → C7 ingestion contract:
# @relation implements:R-100-080 R-100-081
# =============================================================================

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from ay_platform_core.c7_memory.models import (
    ChunkPublic,
    EntityEmbedRequest,
    KGExtractionResult,
    QuotaStatus,
    RetrievalRequest,
    RetrievalResponse,
    SourceIngestRequest,
    SourceListResponse,
    SourcePublic,
)
from ay_platform_core.c7_memory.service import MemoryService, get_service

router = APIRouter(tags=["memory"])

# ---------------------------------------------------------------------------
# RBAC helpers — identical pattern to C3/C4/C5
# ---------------------------------------------------------------------------


def _require_actor(x_user_id: str | None = Header(default=None)) -> str:
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id header missing (forward-auth not applied)",
        )
    return x_user_id


def _require_tenant(x_tenant_id: str | None = Header(default=None)) -> str:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Tenant-Id header missing",
        )
    return x_tenant_id


def _require_role(
    x_user_roles: str | None,
    required: tuple[str, ...],
) -> None:
    roles = {r.strip() for r in (x_user_roles or "").split(",") if r.strip()}
    if not roles.intersection(required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"requires one of: {', '.join(required)}",
        )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/memory/retrieve",
    response_model=RetrievalResponse,
)
async def retrieve(
    payload: RetrievalRequest,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    service: MemoryService = Depends(get_service),
) -> RetrievalResponse:
    return await service.retrieve(payload, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Sources (admin/operator path — production upload goes via C12)
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/memory/projects/{project_id}/sources",
    response_model=SourcePublic,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_source(
    project_id: str,
    payload: SourceIngestRequest,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: MemoryService = Depends(get_service),
) -> SourcePublic:
    # v1 admin-only direct ingest — production upload path is C12.
    _require_role(x_user_roles, required=("project_editor", "project_owner", "admin"))
    if payload.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="payload.project_id does not match URL project_id",
        )
    return await service.ingest_source(payload, tenant_id=tenant_id)


@router.post(
    "/api/v1/memory/projects/{project_id}/sources/upload",
    response_model=SourcePublic,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    project_id: str,
    file: UploadFile = File(..., description="Raw file bytes (PDF/MD/HTML/DOCX/TXT)."),
    source_id: str = Form(..., description="Caller-supplied unique source id."),
    mime_type: str = Form(..., description="MIME type — must match a registered parser."),
    actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: MemoryService = Depends(get_service),
) -> SourcePublic:
    """Multipart file upload (Phase B of v1 plan).

    - Same role gate as JSON ingest: `project_editor` / `project_owner` /
      `admin`. `tenant_manager` excluded by E-100-002 v2.
    - Stores raw bytes in MinIO under
      `sources/{tenant_id}/{project_id}/{source_id}{.ext}` for audit /
      re-parse, then runs parse → chunk → embed → index.
    - Body cap: `c7_max_upload_bytes` (default 50 MiB) — exceeding
      yields 413.
    - Unsupported `mime_type` yields 415; corrupt bytes (encrypted
      PDF, malformed DOCX) yield 422.
    """
    _require_role(x_user_roles, required=("project_editor", "project_owner", "admin"))
    content_bytes = await file.read()
    return await service.ingest_uploaded_source(
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source_id,
        mime_type=mime_type,
        uploaded_by=actor,
        content_bytes=content_bytes,
    )


@router.post(
    "/api/v1/memory/projects/{project_id}/sources/{source_id}/extract-kg",
    response_model=KGExtractionResult,
    status_code=status.HTTP_200_OK,
)
async def extract_kg(
    project_id: str,
    source_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: MemoryService = Depends(get_service),
) -> KGExtractionResult:
    """Phase F.1 — extract entities + relations from an existing source
    via the C8 LLM gateway. Same role gate as `/sources` ingest:
    `project_editor` / `project_owner` / `admin`. `tenant_manager`
    excluded by E-100-002 v2."""
    _require_role(x_user_roles, required=("project_editor", "project_owner", "admin"))
    return await service.extract_kg(
        tenant_id=tenant_id, project_id=project_id, source_id=source_id,
    )


@router.get(
    "/api/v1/memory/projects/{project_id}/sources",
    response_model=SourceListResponse,
)
async def list_sources(
    project_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    service: MemoryService = Depends(get_service),
) -> SourceListResponse:
    return await service.list_sources(tenant_id, project_id)


@router.get(
    "/api/v1/memory/projects/{project_id}/sources/{source_id}",
    response_model=SourcePublic,
)
async def get_source(
    project_id: str,
    source_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    service: MemoryService = Depends(get_service),
) -> SourcePublic:
    return await service.get_source(tenant_id, project_id, source_id)


@router.get(
    "/api/v1/memory/projects/{project_id}/sources/{source_id}/blob",
    responses={
        200: {"description": "Raw source bytes streamed back to the caller."},
        404: {"description": "Source row exists but its blob is missing."},
        503: {"description": "Blob storage not configured (no MinIO wired)."},
    },
)
async def download_source_blob(
    project_id: str,
    source_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    service: MemoryService = Depends(get_service),
) -> Response:
    """Stream the raw uploaded file from MinIO. Same project-scope auth
    as `GET /sources/{source_id}` (its metadata sibling). The
    `Content-Disposition` header carries a synthesised filename so
    browsers can download with a sensible name.

    v1: full bytes loaded into memory then returned (capped at
    `C7_MAX_UPLOAD_BYTES`, default 50 MiB). True streaming chunks
    deferred until uploads exceed that budget.
    """
    blob, mime_type, filename = await service.download_source(
        tenant_id, project_id, source_id,
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=blob, media_type=mime_type, headers=headers)


@router.delete(
    "/api/v1/memory/projects/{project_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_source(
    project_id: str,
    source_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: MemoryService = Depends(get_service),
) -> None:
    # R-400-070: source deletion requires project_owner or admin.
    _require_role(x_user_roles, required=("project_owner", "admin"))
    await service.delete_source(tenant_id, project_id, source_id)


# ---------------------------------------------------------------------------
# Entity embedding — normally event-driven; exposed as admin endpoint for
# tests and manual re-embed operations.
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/memory/entities/embed",
    response_model=ChunkPublic,
    status_code=status.HTTP_201_CREATED,
)
async def embed_entity(
    payload: EntityEmbedRequest,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: MemoryService = Depends(get_service),
) -> ChunkPublic:
    _require_role(x_user_roles, required=("admin",))
    return await service.embed_entity(payload, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/memory/projects/{project_id}/quota",
    response_model=QuotaStatus,
)
async def quota(
    project_id: str,
    _user: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    service: MemoryService = Depends(get_service),
) -> QuotaStatus:
    return await service.quota(tenant_id, project_id)


# ---------------------------------------------------------------------------
# Refresh — deferred to a follow-up (R-400-060/061): stub 501.
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/memory/projects/{project_id}/refresh",
    response_model=None,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def refresh(
    project_id: str,
    _user: str = Depends(_require_actor),
    x_user_roles: str | None = Header(default=None),
) -> None:
    _ = project_id
    _require_role(x_user_roles, required=("admin",))
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="memory refresh deferred to a follow-up (R-400-060/061)",
    )


@router.get(
    "/api/v1/memory/refresh/{job_id}",
    response_model=None,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
)
async def refresh_status(
    job_id: str,
    _user: str = Depends(_require_actor),
) -> None:
    _ = job_id
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="memory refresh deferred to a follow-up (R-400-060/061)",
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/memory/health",
    response_model=None,
)
async def health(
    service: MemoryService = Depends(get_service),
) -> dict[str, str]:
    # Minimal liveness — the service dependency will 503 if not initialised.
    _ = service
    return {"status": "ok"}
