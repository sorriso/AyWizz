# =============================================================================
# File: main.py
# Version: 3
# Path: ay_platform_core/src/ay_platform_core/c2_auth/main.py
# Description: FastAPI app factory for C2 Auth Service. Used by the
#              production container (uvicorn ay_platform_core.c2_auth.main:app)
#              and by e2e/system tests that want to spin a real HTTP surface.
#              Config is read from env-vars via AuthConfig. Arango collections
#              are bootstrapped during the lifespan; in `local` auth mode an
#              admin user is also bootstrapped from C2_LOCAL_ADMIN_*
#              (R-100-118 v2).
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
from ay_platform_core.c2_auth.models import RBACGlobalRole, UserInternal, UserStatus
from ay_platform_core.c2_auth.modes.local_mode import LocalMode
from ay_platform_core.c2_auth.projects_router import router as projects_router
from ay_platform_core.c2_auth.router import router
from ay_platform_core.c2_auth.service import AuthService
from ay_platform_core.c2_auth.service import get_service as c2_get_service
from ay_platform_core.observability import (
    TraceContextMiddleware,
    configure_logging,
)
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
        yield

    app = FastAPI(title="C2 Auth Service", lifespan=lifespan)
    app.add_middleware(TraceContextMiddleware, sample_rate=log_cfg.trace_sample_rate)
    app.include_router(router, prefix="/auth")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(projects_router, prefix="/api/v1/projects")
    service = AuthService(cfg, repo)
    app.dependency_overrides[c2_get_service] = lambda: service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c2_auth"}

    return app


app = create_app()
