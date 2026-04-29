# =============================================================================
# File: main.py
# Version: 4
# Path: ay_platform_core/src/ay_platform_core/c2_auth/main.py
# Description: FastAPI app factory for C2 Auth Service. Used by the
#              production container (uvicorn ay_platform_core.c2_auth.main:app)
#              and by e2e/system tests that want to spin a real HTTP surface.
#              Config is read from env-vars via AuthConfig. Arango collections
#              are bootstrapped during the lifespan; in `local` auth mode an
#              admin user is also bootstrapped from C2_LOCAL_ADMIN_*
#              (R-100-118 v2).
#
#              v4: adds `_ensure_demo_seed()` for the manual-test stack
#              (gated by `C2_DEMO_SEED_ENABLED`). Pre-provisions a
#              complete scenario : 1 tenant (`tenant-test`), 4 users
#              (super-root / tenant-admin / project-editor /
#              project-viewer), 1 project (`project-test`), 2 project
#              grants. Idempotent ; runs after admin/tenant_manager
#              bootstraps so the seeded users coexist with them.
#              Production overlays leave the flag False.
#
#              v3: mounts admin_router at `/admin` (tenant lifecycle,
#              tenant_manager only) and projects_router at
#              `/api/v1/projects` (project lifecycle, admin / project_owner).
#
# @relation implements:R-100-030
# @relation implements:R-100-118
# =============================================================================

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from ay_platform_core.c2_auth.admin_router import router as admin_router
from ay_platform_core.c2_auth.config import AuthConfig
from ay_platform_core.c2_auth.db.repository import AuthRepository
from ay_platform_core.c2_auth.models import (
    RBACGlobalRole,
    RBACProjectRole,
    UserInternal,
    UserStatus,
)
from ay_platform_core.c2_auth.modes.local_mode import LocalMode
from ay_platform_core.c2_auth.projects_router import router as projects_router
from ay_platform_core.c2_auth.router import router
from ay_platform_core.c2_auth.service import AuthService
from ay_platform_core.c2_auth.service import get_service as c2_get_service
from ay_platform_core.c2_auth.ux_router import ux_router
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
from ay_platform_core.observability.auth_guard import AuthGuardMiddleware
from ay_platform_core.observability.config import LoggingSettings

_log = logging.getLogger("c2_auth.bootstrap")


async def _ensure_local_admin(repo: AuthRepository, cfg: AuthConfig) -> None:
    """Create the bootstrap admin user if `auth_mode == "local"` and absent.

    Idempotent: silently skips if a user with the configured username
    already exists. Roles default to global ADMIN.
    """
    if cfg.auth_mode != "local":
        return
    existing = await repo.get_user_by_username(cfg.local_admin_username)
    if existing is not None:
        _log.info("local admin %r already present, skipping", cfg.local_admin_username)
        return
    user = UserInternal(
        user_id=f"admin-{cfg.local_admin_username}",
        username=cfg.local_admin_username,
        tenant_id="default",
        roles=[RBACGlobalRole.ADMIN],
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        argon2id_hash=LocalMode.hash_password(cfg.local_admin_password),
    )
    await repo.insert_user(user)
    _log.info("bootstrapped local admin %r", cfg.local_admin_username)


async def _ensure_local_tenant_manager(
    repo: AuthRepository, cfg: AuthConfig,
) -> None:
    """Create the bootstrap tenant_manager (super-root) if
    `auth_mode == "local"` AND both `local_tenant_manager_*` config
    fields are non-empty. Idempotent.

    Per E-100-002 v2 the tenant_manager is **content-blind** —
    tenant lifecycle ops only (create/list/delete tenants), no
    access to projects / sources / conversations. Single-tenant
    deployments leave both fields empty and rely on admin alone.
    """
    if cfg.auth_mode != "local":
        return
    if not (
        cfg.local_tenant_manager_username
        and cfg.local_tenant_manager_password
    ):
        return
    existing = await repo.get_user_by_username(
        cfg.local_tenant_manager_username,
    )
    if existing is not None:
        _log.info(
            "local tenant_manager %r already present, skipping",
            cfg.local_tenant_manager_username,
        )
        return
    user = UserInternal(
        user_id=f"tenant-manager-{cfg.local_tenant_manager_username}",
        username=cfg.local_tenant_manager_username,
        # tenant_manager is cross-tenant by design — `tenant_id` is
        # decorative here. Same "default" tag the admin gets, for
        # symmetry.
        tenant_id="default",
        roles=[RBACGlobalRole.TENANT_MANAGER],
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        argon2id_hash=LocalMode.hash_password(
            cfg.local_tenant_manager_password,
        ),
    )
    await repo.insert_user(user)
    _log.info(
        "bootstrapped local tenant_manager %r",
        cfg.local_tenant_manager_username,
    )


async def _ensure_demo_seed(repo: AuthRepository, cfg: AuthConfig) -> None:
    """Pre-provision a complete manual-test scenario : 1 tenant +
    4 users (super-root / tenant-admin / project-editor /
    project-viewer) + 1 project + 2 project grants. Idempotent ;
    every step pre-checks existence before insert.

    Gated by `auth_mode == 'local'` AND `demo_seed_enabled`.
    PRODUCTION overlays SHALL leave `demo_seed_enabled` False —
    the demo accounts have well-known passwords by design.

    The companion flag `ux_dev_mode_enabled` controls whether the
    credentials are surfaced on `/ux/config`. The two flags are
    independent (defense-in-depth) : staging may seed without
    exposing ; the local stack overlay flips both to True.
    """
    if cfg.auth_mode != "local":
        return
    if not cfg.demo_seed_enabled:
        return

    now = datetime.now(UTC)
    tenant_id = cfg.demo_seed_tenant_id
    project_id = cfg.demo_seed_project_id

    # 1. Tenant — required parent for project + tenant-scoped users.
    if await repo.get_tenant(tenant_id) is None:
        await repo.insert_tenant(tenant_id, cfg.demo_seed_tenant_name, now)
        _log.info("demo seed: created tenant %r", tenant_id)

    # 2. Users (4) — pre-check by username. user_id is deterministic
    # so re-runs across restarts re-find the same record.
    users_to_seed: list[tuple[str, str, str, str, RBACGlobalRole]] = [
        # (username, password, user_id, user_tenant_id, role)
        # Super-root is cross-tenant by design — `tenant_id` is a
        # decorative tag, mirror admin/tenant_manager bootstrap.
        (
            cfg.demo_seed_superroot_username,
            cfg.demo_seed_superroot_password,
            "demo-superroot",
            "default",
            RBACGlobalRole.TENANT_MANAGER,
        ),
        (
            cfg.demo_seed_tenant_admin_username,
            cfg.demo_seed_tenant_admin_password,
            "demo-tenant-admin",
            tenant_id,
            RBACGlobalRole.ADMIN,
        ),
        (
            cfg.demo_seed_project_editor_username,
            cfg.demo_seed_project_editor_password,
            "demo-project-editor",
            tenant_id,
            RBACGlobalRole.USER,
        ),
        (
            cfg.demo_seed_project_viewer_username,
            cfg.demo_seed_project_viewer_password,
            "demo-project-viewer",
            tenant_id,
            RBACGlobalRole.USER,
        ),
    ]
    for username, password, user_id, user_tenant, role in users_to_seed:
        if await repo.get_user_by_username(username) is not None:
            continue
        user = UserInternal(
            user_id=user_id,
            username=username,
            tenant_id=user_tenant,
            roles=[role],
            status=UserStatus.ACTIVE,
            created_at=now,
            argon2id_hash=LocalMode.hash_password(password),
        )
        await repo.insert_user(user)
        _log.info(
            "demo seed: created user %r (id=%s, role=%s)",
            username, user_id, role.value,
        )

    # 3. Project — created by the tenant-admin user. Pre-check by id.
    if await repo.get_project(project_id) is None:
        await repo.insert_project(
            project_id,
            tenant_id,
            cfg.demo_seed_project_name,
            now,
            "demo-tenant-admin",
        )
        _log.info(
            "demo seed: created project %r in tenant %r",
            project_id, tenant_id,
        )

    # 4. Project grants — `grant_project_role` uses `overwrite=True`
    # so re-running is safe (the role assignment doc is keyed
    # `{user_id}:{project_id}`).
    grants_to_seed: list[tuple[str, RBACProjectRole]] = [
        ("demo-project-editor", RBACProjectRole.EDITOR),
        ("demo-project-viewer", RBACProjectRole.VIEWER),
    ]
    for grantee_id, project_role in grants_to_seed:
        await repo.grant_project_role(grantee_id, project_id, project_role.value)
        _log.info(
            "demo seed: granted %s on project %r to user %s",
            project_role.value, project_id, grantee_id,
        )


def create_app(config: AuthConfig | None = None) -> FastAPI:
    cfg = config or AuthConfig()
    log_cfg = LoggingSettings()
    configure_logging(component="c2_auth", settings=log_cfg)
    repo = AuthRepository.from_config(
        cfg.arango_url,
        cfg.arango_db,
        cfg.arango_username,
        cfg.arango_password,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await repo.ensure_collections()
        await _ensure_local_admin(repo, cfg)
        await _ensure_local_tenant_manager(repo, cfg)
        await _ensure_demo_seed(repo, cfg)
        yield

    app = FastAPI(title="C2 Auth Service", lifespan=lifespan)
    # AuthGuardMiddleware (innermost, runs after TraceContext) — C2's
    # public auth surface (login/token/verify/config + the UX
    # bootstrap config) is exempt; every other path requires
    # X-User-Id propagated by Traefik forward-auth.
    app.add_middleware(
        AuthGuardMiddleware,
        component="c2_auth",
        exempt_prefixes=[
            "/health",
            "/auth/config",
            "/auth/login",
            "/auth/token",
            "/auth/verify",
            "/ux/config",
        ],
    )
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router, prefix="/auth")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(projects_router, prefix="/api/v1/projects")
    app.include_router(ux_router, prefix="/ux")
    service = AuthService(cfg, repo)
    app.dependency_overrides[c2_get_service] = lambda: service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c2_auth"}

    return app


app = create_app()
