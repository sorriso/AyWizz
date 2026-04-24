# =============================================================================
# File: main.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c2_auth/main.py
# Description: FastAPI app factory for C2 Auth Service. Used by the
#              production container (uvicorn ay_platform_core.c2_auth.main:app)
#              and by e2e/system tests that want to spin a real HTTP surface.
#              Config is read from env-vars via AuthConfig. Arango collections
#              are bootstrapped during the lifespan.
#
# @relation implements:R-100-030
# =============================================================================

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ay_platform_core.c2_auth.config import AuthConfig
from ay_platform_core.c2_auth.db.repository import AuthRepository
from ay_platform_core.c2_auth.router import router
from ay_platform_core.c2_auth.service import AuthService
from ay_platform_core.c2_auth.service import get_service as c2_get_service


def create_app(config: AuthConfig | None = None) -> FastAPI:
    cfg = config or AuthConfig()
    repo = AuthRepository.from_config(
        cfg.arango_url,
        cfg.arango_db_name,
        cfg.arango_username,
        cfg.arango_password,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await repo.ensure_collections()
        yield

    app = FastAPI(title="C2 Auth Service", lifespan=lifespan)
    app.include_router(router, prefix="/auth")
    service = AuthService(cfg, repo)
    app.dependency_overrides[c2_get_service] = lambda: service

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "component": "c2_auth"}

    return app


app = create_app()
