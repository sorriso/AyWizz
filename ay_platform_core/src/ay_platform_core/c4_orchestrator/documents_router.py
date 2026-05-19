# =============================================================================
# File: documents_router.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c4_orchestrator/documents_router.py
# Description: REST surface for the chat-direct DocGen document API
#              (D-015). CRUD on the project's `live-docs` artifact run :
#                POST   /api/v1/projects/{pid}/documents       — create/overwrite
#                PUT    /api/v1/projects/{pid}/documents/{path} — update
#                GET    /api/v1/projects/{pid}/documents        — list
#                GET    /api/v1/projects/{pid}/documents/{path} — read
#                DELETE /api/v1/projects/{pid}/documents/{path} — delete
#
#              These endpoints are the v1 mutation surface invoked by
#              the C3 conversation's tool calls (Phase 2.C.2). They
#              are profile-agnostic in code ; the DocGen profile uses
#              them, the migration to the synthesis-v4 pipeline path
#              (v2) reuses the same surface from OpenHands-in-C15.
#
#              Forward-auth identity model identical to artifacts_router
#              (X-User-Id / X-Tenant-Id / X-User-Roles). `tenant_manager`
#              is rejected — documents are tenant content (E-100-002 v2).
#
# @relation implements:R-200-153
# @relation implements:R-200-154
# @relation implements:R-200-155
# @relation implements:R-200-156
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ay_platform_core.c4_orchestrator.artifacts_router import (
    _get_service,
    _reject_tenant_manager,
    _require_actor,
    _require_tenant,
)
from ay_platform_core.c4_orchestrator.artifacts_service import ArtifactsService

router = APIRouter(tags=["documents"])


# ---------------------------------------------------------------------------
# Wire models
# ---------------------------------------------------------------------------


class DocumentWrite(BaseModel):
    """Body of POST /documents — create or overwrite. `path` follows
    the R-200-130 convention (POSIX relative, no `..`, no leading
    `/`). `content` is the full UTF-8 text body."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    content: str


class DocumentUpdate(BaseModel):
    """Body of PUT /documents/{path} — `path` comes from the URL, so
    only the new content is in the body."""

    model_config = ConfigDict(extra="forbid")

    content: str


class DocumentRef(BaseModel):
    """One row of the documents listing + the create/update response."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int = Field(ge=0)


class DocumentList(BaseModel):
    """Wrapper for the documents listing — forward-compat room for
    pagination cursors, same reasoning as `ArtifactRunList`."""

    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentRef]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/projects/{project_id}/documents",
    response_model=DocumentRef,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    project_id: str,
    body: DocumentWrite,
    _actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: ArtifactsService = Depends(_get_service),
) -> DocumentRef:
    """Create or overwrite a document. Idempotent on the same path
    (overwrites). Triggers an incremental Gitea push (one commit)."""
    _reject_tenant_manager(x_user_roles)
    result = await service.write_document(
        project_id=project_id,
        tenant_id=tenant_id,
        path=body.path,
        content=body.content,
    )
    return DocumentRef(**result)


@router.put(
    "/api/v1/projects/{project_id}/documents/{path:path}",
    response_model=DocumentRef,
)
async def update_document(
    project_id: str,
    path: str,
    body: DocumentUpdate,
    _actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: ArtifactsService = Depends(_get_service),
) -> DocumentRef:
    """Overwrite an existing document at `{path}`. Same effect as POST
    with that path — separate verb so the conversation tool surface
    can distinguish create vs update intent in its audit trail."""
    _reject_tenant_manager(x_user_roles)
    result = await service.write_document(
        project_id=project_id,
        tenant_id=tenant_id,
        path=path,
        content=body.content,
    )
    return DocumentRef(**result)


@router.get(
    "/api/v1/projects/{project_id}/documents",
    response_model=DocumentList,
)
async def list_documents(
    project_id: str,
    _actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: ArtifactsService = Depends(_get_service),
) -> DocumentList:
    """List every document path in the project's live-docs corpus.
    Empty list when no document has been created yet."""
    _reject_tenant_manager(x_user_roles)
    rows = await service.list_documents(
        project_id=project_id, tenant_id=tenant_id,
    )
    return DocumentList(documents=[DocumentRef(**r) for r in rows])


@router.get("/api/v1/projects/{project_id}/documents/{path:path}")
async def read_document(
    project_id: str,
    path: str,
    _actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: ArtifactsService = Depends(_get_service),
) -> Response:
    """Stream a document's content back. 404 when missing, 400 on a
    malformed path."""
    _reject_tenant_manager(x_user_roles)
    blob = await service.read_document(
        project_id=project_id, tenant_id=tenant_id, path=path,
    )
    filename = path.rsplit("/", 1)[-1] or "document"
    return Response(
        content=blob.data,
        media_type=blob.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=0, must-revalidate",
        },
    )


@router.delete(
    "/api/v1/projects/{project_id}/documents/{path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    project_id: str,
    path: str,
    _actor: str = Depends(_require_actor),
    tenant_id: str = Depends(_require_tenant),
    x_user_roles: str | None = Header(default=None),
    service: ArtifactsService = Depends(_get_service),
) -> Response:
    """Delete a document from MinIO. 404 when the path is unknown.
    Gitea history is intentionally retained (audit ; D-015)."""
    _reject_tenant_manager(x_user_roles)
    await service.delete_document(
        project_id=project_id, tenant_id=tenant_id, path=path,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
