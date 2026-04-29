# =============================================================================
# File: _catalog.py
# Version: 1
# Path: ay_platform_core/tests/e2e/auth_matrix/_catalog.py
# Description: SINGLE SOURCE OF TRUTH for the auth x role x scope test matrix.
#              Every HTTP route exposed by any platform component SHALL be
#              listed here exactly once. The coherence test
#              `tests/coherence/test_route_catalog.py` pins live FastAPI
#              routes to this catalog and fails the build on drift.
#
#              Adding a new endpoint = adding ONE EndpointSpec entry. The
#              parametrized test files
#              (`test_anonymous_access.py`, `test_role_matrix.py`,
#              `test_isolation.py`) auto-cover the new endpoint along
#              every dimension; only `test_backend_state.py` requires
#              hand-written assertions per resource type.
#
# Reference: E-100-002 v2 (5-role hierarchy), CLAUDE.md §13.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    """Where the resource lives in the tenant/project hierarchy."""

    NONE = "none"
    """Global / open endpoint — no tenant or project constraint."""

    TENANT = "tenant"
    """Scoped to the X-Tenant-Id header. Cross-tenant access SHALL leak nothing."""

    PROJECT = "project"
    """Scoped to a {project_id} path segment within an X-Tenant-Id."""


class Auth(StrEnum):
    """Authentication requirement of the endpoint."""

    OPEN = "open"
    """No auth required (health, login, config, etc.)."""

    AUTHENTICATED = "authenticated"
    """Requires X-User-Id + X-Tenant-Id; no role gate."""

    ROLE_GATED = "role_gated"
    """Requires X-User-Id + X-Tenant-Id + at least one of `accept_roles`."""


class Backend(StrEnum):
    """Persistence layer the endpoint reads / writes (for backend assertions)."""

    NONE = "none"
    ARANGO = "arango"
    MINIO = "minio"
    BOTH = "both"


@dataclass(frozen=True)
class EndpointSpec:
    """One HTTP route, fully specified for the test matrix.

    Every endpoint in the platform SHALL have exactly one EndpointSpec
    entry in `ENDPOINTS` below.
    """

    component: str
    method: str
    path: str
    auth: Auth
    success_status: int
    scope: Scope = Scope.NONE
    accept_roles: tuple[str, ...] = ()
    """For ROLE_GATED endpoints: any of these roles passes the gate.

    Use `()` for AUTHENTICATED (no role gate) and OPEN (no auth at all).
    Project-scoped roles flow via the user's `project_scopes` claim.
    """
    accept_global_roles: tuple[str, ...] = ()
    """Global roles (admin, tenant_admin, tenant_manager) that ALSO pass
    this gate, in addition to project-scoped `accept_roles`. The audit
    documents that for most project-scoped operations, `admin` /
    `tenant_admin` are also accepted."""
    backend: Backend = Backend.NONE
    backend_collection: str | None = None
    backend_bucket: str | None = None
    excluded_global_roles: tuple[str, ...] = ()
    """Global roles that SHALL be REJECTED by this endpoint even though
    they are present in the user's claims. Used for `tenant_manager`
    on content endpoints (E-100-002 v2: tenant_manager is content-blind)."""
    notes: str = ""


# ---------------------------------------------------------------------------
# Catalog
#
# Order: by component, then by method, then by path. Keep this order
# stable so generated documentation diffs cleanly.
# ---------------------------------------------------------------------------


_C2_AUTH: list[EndpointSpec] = [
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/auth/config",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/ux/config",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/auth/token",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
        notes="Local mode login — username/password → JWT.",
    ),
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/auth/login",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
        notes="Alias of /auth/token (form-style endpoint).",
    ),
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/auth/verify",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
        notes="Forward-auth probe; returns user identity.",
    ),
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/auth/logout",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=204,
    ),
    # User management — admin / tenant_admin only. tenant_manager is
    # excluded by E-100-002 v2: managing users IS tenant content.
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/auth/users",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=201,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_users",
    ),
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/auth/users/{user_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=200,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c2_auth",
        method="PATCH",
        path="/auth/users/{user_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=200,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_users",
    ),
    EndpointSpec(
        component="c2_auth",
        method="DELETE",
        path="/auth/users/{user_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=204,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_users",
    ),
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/auth/users/{user_id}/reset-password",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=204,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
    ),
    # Session management — `admin` ONLY (no tenant_admin in v1; cross-
    # tenant view of all platform sessions).
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/auth/sessions",
        auth=Auth.ROLE_GATED,
        scope=Scope.NONE,
        success_status=200,
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c2_auth",
        method="DELETE",
        path="/auth/sessions/{session_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.NONE,
        success_status=204,
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    # Tenant lifecycle (Phase A) — tenant_manager super-root ONLY.
    # These are the platform's only endpoints where tenant_manager is
    # the EXCLUSIVE accepted role: tenant lifecycle is the operator
    # surface, not tenant content.
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/admin/tenants",
        auth=Auth.ROLE_GATED,
        scope=Scope.NONE,
        success_status=201,
        accept_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_tenants",
    ),
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/admin/tenants",
        auth=Auth.ROLE_GATED,
        scope=Scope.NONE,
        success_status=200,
        accept_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c2_auth",
        method="DELETE",
        path="/admin/tenants/{tenant_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.NONE,
        success_status=204,
        accept_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_tenants",
    ),
    # Project lifecycle (Phase A) — admin / tenant_admin / project_owner
    # depending on operation. tenant_manager is EXCLUDED because
    # projects are tenant content (E-100-002 v2 separation of duties).
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/api/v1/projects",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=201,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_projects",
    ),
    EndpointSpec(
        component="c2_auth",
        method="GET",
        path="/api/v1/projects",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
        notes=(
            "Any authenticated user lists projects in their tenant; "
            "tenant_manager is rejected in the handler since listing "
            "tenant projects is tenant content."
        ),
    ),
    EndpointSpec(
        component="c2_auth",
        method="DELETE",
        path="/api/v1/projects/{project_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=204,
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_projects",
    ),
    EndpointSpec(
        component="c2_auth",
        method="POST",
        path="/api/v1/projects/{project_id}/members/{user_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=204,
        accept_roles=("project_owner",),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_role_assignments",
    ),
    EndpointSpec(
        component="c2_auth",
        method="DELETE",
        path="/api/v1/projects/{project_id}/members/{user_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=204,
        accept_roles=("project_owner",),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c2_role_assignments",
    ),
]


_C5_REQUIREMENTS: list[EndpointSpec] = [
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/documents",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
        backend=Backend.ARANGO,
        backend_collection="c5_documents",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="POST",
        path="/api/v1/projects/{project_id}/requirements/documents",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=201,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c5_documents",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/documents/{slug}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
        backend=Backend.ARANGO,
        backend_collection="c5_documents",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="PUT",
        path="/api/v1/projects/{project_id}/requirements/documents/{slug}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=200,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c5_documents",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="DELETE",
        path="/api/v1/projects/{project_id}/requirements/documents/{slug}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=204,
        accept_roles=("project_owner",),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c5_documents",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/entities",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
        backend=Backend.ARANGO,
        backend_collection="c5_entities",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/entities/{entity_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
        backend=Backend.ARANGO,
        backend_collection="c5_entities",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="PATCH",
        path="/api/v1/projects/{project_id}/requirements/entities/{entity_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=200,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c5_entities",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="DELETE",
        path="/api/v1/projects/{project_id}/requirements/entities/{entity_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=204,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c5_entities",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/entities/{entity_id}/history",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/entities/{entity_id}/versions/{version}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=501,
        notes="Stub — point-in-time export deferred to v2.",
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/relations",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/tailorings",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c5_requirements",
        method="POST",
        path="/api/v1/projects/{project_id}/requirements/reindex",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=202,
        accept_roles=("project_owner",),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/reindex/{job_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c5_requirements",
        method="POST",
        path="/api/v1/projects/{project_id}/requirements/reconcile",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=200,
        accept_roles=("project_owner",),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c5_requirements",
        method="GET",
        path="/api/v1/projects/{project_id}/requirements/export",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c5_requirements",
        method="POST",
        path="/api/v1/projects/{project_id}/requirements/import",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=501,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin", "tenant_admin"),
        excluded_global_roles=("tenant_manager",),
        notes="Stub — import format negotiation deferred to v2.",
    ),
]


_C7_MEMORY: list[EndpointSpec] = [
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/retrieve",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/projects/{project_id}/sources",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=201,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c7_sources",
    ),
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/projects/{project_id}/sources/upload",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=201,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.BOTH,
        backend_collection="memory_sources",
        backend_bucket="memory",
        notes=(
            "Multipart file upload (Phase B). Stores raw blob in MinIO + "
            "indexes parsed text into Arango. Body cap = "
            "C7_MAX_UPLOAD_BYTES (default 50 MiB)."
        ),
    ),
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/projects/{project_id}/sources/{source_id}/extract-kg",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=200,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="memory_kg_entities",
        notes=(
            "Phase F.1 — LLM-based entity + relation extraction on an "
            "existing source. Persists to memory_kg_entities (vertex) "
            "and memory_kg_relations (edge). Hybrid retrieval (F.2) "
            "deferred to v1.5."
        ),
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/projects/{project_id}/sources",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/projects/{project_id}/sources/{source_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/projects/{project_id}/sources/{source_id}/blob",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c7_memory",
        method="DELETE",
        path="/api/v1/memory/projects/{project_id}/sources/{source_id}",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=204,
        accept_roles=("project_owner",),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
        backend=Backend.ARANGO,
        backend_collection="c7_sources",
    ),
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/entities/embed",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=201,
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/projects/{project_id}/quota",
        auth=Auth.AUTHENTICATED,
        scope=Scope.PROJECT,
        success_status=200,
    ),
    EndpointSpec(
        component="c7_memory",
        method="POST",
        path="/api/v1/memory/projects/{project_id}/refresh",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=501,
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
        notes="Stub — refresh job deferred (R-400-060/061).",
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/refresh/{job_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=501,
        notes="Stub — refresh job status deferred.",
    ),
    EndpointSpec(
        component="c7_memory",
        method="GET",
        path="/api/v1/memory/health",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
    ),
]


_C6_VALIDATION: list[EndpointSpec] = [
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/plugins",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/domains",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c6_validation",
        method="POST",
        path="/api/v1/validation/runs",
        auth=Auth.ROLE_GATED,
        scope=Scope.PROJECT,
        success_status=202,
        accept_roles=("project_editor", "project_owner"),
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/runs/{run_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/runs/{run_id}/findings",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/findings/{finding_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c6_validation",
        method="GET",
        path="/api/v1/validation/health",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
    ),
]


_C3_CONVERSATION: list[EndpointSpec] = [
    EndpointSpec(
        component="c3_conversation",
        method="GET",
        path="/api/v1/conversations",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c3_conversation",
        method="POST",
        path="/api/v1/conversations",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=201,
        backend=Backend.ARANGO,
        backend_collection="c3_conversations",
    ),
    EndpointSpec(
        component="c3_conversation",
        method="GET",
        path="/api/v1/conversations/{conversation_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c3_conversation",
        method="PATCH",
        path="/api/v1/conversations/{conversation_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
        backend=Backend.ARANGO,
        backend_collection="c3_conversations",
    ),
    EndpointSpec(
        component="c3_conversation",
        method="DELETE",
        path="/api/v1/conversations/{conversation_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=204,
        backend=Backend.ARANGO,
        backend_collection="c3_conversations",
    ),
    EndpointSpec(
        component="c3_conversation",
        method="GET",
        path="/api/v1/conversations/{conversation_id}/messages",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c3_conversation",
        method="POST",
        path="/api/v1/conversations/{conversation_id}/messages",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c3_conversation",
        method="GET",
        path="/api/v1/conversations/{conversation_id}/events",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
]


_C4_ORCHESTRATOR: list[EndpointSpec] = [
    EndpointSpec(
        component="c4_orchestrator",
        method="POST",
        path="/api/v1/orchestrator/runs",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=201,
        backend=Backend.ARANGO,
        backend_collection="c4_runs",
    ),
    EndpointSpec(
        component="c4_orchestrator",
        method="GET",
        path="/api/v1/orchestrator/runs/{run_id}",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c4_orchestrator",
        method="POST",
        path="/api/v1/orchestrator/runs/{run_id}/feedback",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
    ),
    EndpointSpec(
        component="c4_orchestrator",
        method="POST",
        path="/api/v1/orchestrator/runs/{run_id}/resume",
        auth=Auth.ROLE_GATED,
        scope=Scope.TENANT,
        success_status=200,
        accept_global_roles=("admin",),
        excluded_global_roles=("tenant_manager",),
    ),
]


_C9_MCP: list[EndpointSpec] = [
    EndpointSpec(
        component="c9_mcp",
        method="POST",
        path="/api/v1/mcp",
        auth=Auth.AUTHENTICATED,
        scope=Scope.TENANT,
        success_status=200,
        notes="JSON-RPC envelope; per-tool role checks happen inside the body.",
    ),
    EndpointSpec(
        component="c9_mcp",
        method="GET",
        path="/api/v1/mcp/tools",
        auth=Auth.AUTHENTICATED,
        scope=Scope.NONE,
        success_status=200,
    ),
    EndpointSpec(
        component="c9_mcp",
        method="GET",
        path="/api/v1/mcp/health",
        auth=Auth.OPEN,
        scope=Scope.NONE,
        success_status=200,
    ),
]


ENDPOINTS: list[EndpointSpec] = [
    *_C2_AUTH,
    *_C3_CONVERSATION,
    *_C4_ORCHESTRATOR,
    *_C5_REQUIREMENTS,
    *_C6_VALIDATION,
    *_C7_MEMORY,
    *_C9_MCP,
]


# ---------------------------------------------------------------------------
# Convenience accessors used by tests + coherence script + doc generator
# ---------------------------------------------------------------------------


def by_component(component: str) -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.component == component]


def role_gated() -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.auth == Auth.ROLE_GATED]


def authenticated_or_role_gated() -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.auth != Auth.OPEN]


def project_scoped() -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.scope == Scope.PROJECT]


def tenant_scoped() -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.scope == Scope.TENANT]


def with_backend() -> list[EndpointSpec]:
    return [e for e in ENDPOINTS if e.backend != Backend.NONE]


def endpoint_id(spec: EndpointSpec) -> str:
    """Stable, human-readable parametrize id."""
    return f"{spec.component}::{spec.method}::{spec.path}"


# Sanity self-check on import: catalog SHALL have unique (component, method,
# path) tuples. A duplicate is almost always a copy-paste bug.
_seen: set[tuple[str, str, str]] = set()
for _e in ENDPOINTS:
    _key = (_e.component, _e.method, _e.path)
    if _key in _seen:
        raise RuntimeError(f"duplicate EndpointSpec in catalog: {_key}")
    _seen.add(_key)
del _seen


# Reserved roles documented in E-100-002 v2 — used by tests to enumerate
# the role universe.
ALL_GLOBAL_ROLES: tuple[str, ...] = (
    "tenant_manager",
    "admin",
    "tenant_admin",
    "user",
)
ALL_PROJECT_ROLES: tuple[str, ...] = (
    "project_owner",
    "project_editor",
    "project_viewer",
)


__all__ = [
    "ALL_GLOBAL_ROLES",
    "ALL_PROJECT_ROLES",
    "ENDPOINTS",
    "Auth",
    "Backend",
    "EndpointSpec",
    "Scope",
    "authenticated_or_role_gated",
    "by_component",
    "endpoint_id",
    "project_scoped",
    "role_gated",
    "tenant_scoped",
    "with_backend",
]
