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
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ay_platform_core.c7_memory.models import (
    ChunkPublic,
    EntityEmbedRequest,
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
